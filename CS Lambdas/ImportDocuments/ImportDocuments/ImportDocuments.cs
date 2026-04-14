using AI_Libraries.SharePoint;
using AI_Libraries.SharePoint.Abstractions;
using AI_Libraries.SharePoint.Enums;
using AI_Libraries.SharePoint.Models;
using AI_Libraries.SharePoint.Utilities;
using AILibraries.Storage.Abstractions;
using AILibraries.Storage.Implementations;
using AILibraries.Storage.Models;
using Amazon.Lambda.Core;
using Amazon.S3;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using DriveInfo = AI_Libraries.SharePoint.Models.DriveInfo;

// Assembly attribute to enable the Lambda function's JSON input to be converted into a .NET class.
[assembly: LambdaSerializer(typeof(Amazon.Lambda.Serialization.SystemTextJson.DefaultLambdaJsonSerializer))]

namespace ImportDocuments;

public class ImportDocuments
{
    public async Task<string> FunctionHandler(ILambdaContext context)
    {
        IConfiguration config = new ConfigurationBuilder()
                                    .SetBasePath(Directory.GetCurrentDirectory())
                                    .AddUserSecrets<ImportDocuments>()
                                    .AddJsonFile("appsettings.json")
                                    .AddEnvironmentVariables()
                                    .Build();

        string? clientId = config.GetValue<string>("clientId");
        string? clientSecret = config.GetValue<string>("clientSecret");
        string? tenantId = config.GetValue<string>("tenantId");
        string? sharePointUrl = config.GetValue<string>("sharepointUrl");
        string? driveName = config.GetValue<string>("driveName");
        string? outputBucket = config.GetValue<string>("outputBucket");
        string? categories = config.GetValue<string>("csvCategories");
        string? sharePointFolderPath = config.GetValue<string>("sharePointFolderPath");

        ExitIfNull(
            context.Logger,
            (nameof(tenantId), tenantId),
            (nameof(clientId), clientId),
            (nameof(clientSecret), clientSecret),
            (nameof(sharePointUrl), sharePointUrl),
            (nameof(driveName), driveName),
            (nameof(outputBucket), outputBucket)
            );

        HashSet<string> categorySet = new();

        if (!string.IsNullOrEmpty(categories))
        {
            foreach (string cat in categories.Split(",", StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
            {
                categorySet.Add(cat);
            }
        }

#if DEBUG
        string? profileName = config.GetValue<string>("awsProfileName");

        IAmazonS3 amazonS3 = await AwsSsoHelper.EnsureSsoLoginAsync(profileName!);
#else
        IAmazonS3 amazonS3 = new AmazonS3Client();
#endif

        var loggerFactory = LoggerFactory.Create(builder =>
        {
            builder.AddConsole();
        });

        IS3Storage storage = S3StorageFactory.Create(
            new S3StorageOptions()
            {
                DefaultBucket = outputBucket
            },
            amazonS3,
            loggerFactory.CreateLogger<S3Storage>()
            );

        ISharePointClientOptions options = new SimpleSharePointClientOptions(
            tenantId!,
            clientId!,
            clientSecret!,
            AzureHostUrls.GovCloud);

        ISharePointClient sharePointClient = SharePointClientFactory.Create(options);

        sharePointUrl = SharePointPathConverter.ToGraphSitepath(sharePointUrl!);

        SiteInfo siteInfo = await sharePointClient.SiteService.GetByPathAsync(sharePointUrl);

        IEnumerable<DriveInfo> drives = await sharePointClient.DriveService.GetDrivesForSiteIdAsync(siteInfo);

        DriveInfo? selectedDrive = drives.FirstOrDefault(d => d.DriveName == driveName);

        if (selectedDrive is null)
        {
            context.Logger.LogError($"No drive with name '{driveName}'");

            Environment.Exit(1);
        }

        context.Logger.LogInformation("Fetching files from SharePoint...");
        string folderPath = "";
        if (!string.IsNullOrEmpty(sharePointFolderPath))
        {
            folderPath = sharePointFolderPath;
        }

        IEnumerable<FileItem> files = await sharePointClient.FileService.GetFilesFromDrive(
            selectedDrive,
            folderPath: folderPath,
            formatKeys: true);

        context.Logger.LogInformation($"Moving files to S3 bucket {outputBucket}");
        foreach (FileItem file in files)
        {
            // Skip over the Business Writings categories that we don't want in the bucket.
            // Will import all categories, if the categorySet is empty.
            if (file.Metadata is not null && file.Metadata.TryGetValue("Category", out object? categoryObject))
            {
                string? cat = categoryObject.ToString()?.Substring(0, 3);
                if (categorySet.Any() && !categorySet.Contains(cat ?? ""))
                {
                    continue;
                }
            }

            string filePath = file.Name;

            if (!string.IsNullOrEmpty(folderPath))
            {
                filePath = Path.Combine(folderPath, filePath);
            }

            await CopyDocumentToBucket(
                outputBucket!,
                storage,
                sharePointClient,
                filePath,
                file);
        }

        return "Import Completed";
    }

    private static async Task CopyDocumentToBucket(string outputBucket, IS3Storage storage, ISharePointClient sharePointClient, string filePath, FileItem file)
    {
        Dictionary<string, string> metadata = new(MetadataHelper.ConvertMetadata(file.Metadata))
        {
            ["Original Document Url"] = file.Path
        };
        IReadOnlyDictionary<string, string> tags = new Dictionary<string, string>() { { "Project", "KnowledgeAssistant" } };

        PutObjectOptions putObjectOptions = new() { Metadata = metadata, Tags = tags };

        using Stream stream = await sharePointClient.FileService.GetFileStreamFromDrive(
            file.DriveId,
            filePath);

        using MemoryStream memStream = new();
        stream.CopyTo(memStream);

        S3ObjectId objectId = ObjectKeyHelper.GetSortObjectKey(outputBucket!, file.Name);

        await storage.PutObjectAsync(objectId, memStream, putObjectOptions);
    }

    private void ExitIfNull(ILambdaLogger logger, params IEnumerable<(string name, string? value)> environmentVariables)
    {
        foreach ((string name, string? value) in environmentVariables)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                logger.LogError($"Missing {name}");
                Environment.Exit(1);
            }
        }
    }
}
