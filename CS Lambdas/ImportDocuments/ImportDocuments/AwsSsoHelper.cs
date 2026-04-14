using System.Diagnostics;
using Amazon;
using Amazon.Runtime;
using Amazon.Runtime.CredentialManagement;
using Amazon.S3;

namespace ImportDocuments;

public static class AwsSsoHelper
{
    public static async Task<IAmazonS3> EnsureSsoLoginAsync(string awsProfileName)
    {
        CredentialProfileStoreChain chain = new();
        
        if (!chain.TryGetAWSCredentials(awsProfileName, out AWSCredentials credentials))
        {
            await TryLoginAsync(awsProfileName);
        }

        IAmazonS3 s3Client = new AmazonS3Client(credentials, RegionEndpoint.USGovCloudWest1);

        try
        {
            await s3Client.ListBucketsAsync();
        }
        catch (AmazonClientException ex) when (ex.Message.Contains("SSO") ||
                ex.Message.Contains("expired") ||
                ex.Message.Contains("token"))
        {
            await TryLoginAsync(awsProfileName);
        }
        
        return s3Client;
    }

    private static async Task TryLoginAsync(string awsProfileName)
    {
        int exitCode = await LoginAsync(awsProfileName);
        if (exitCode != 0)
        {
            Environment.Exit(exitCode);
        }
    }

    private static async Task<int> LoginAsync(string profile)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = "aws",
            Arguments = $"sso login --profile \"{profile}\"",
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = false
        };

        using var process = new Process { StartInfo = startInfo };

        process.Start();

        string output = await process.StandardOutput.ReadToEndAsync();
        Console.WriteLine(output);

        string error = await process.StandardError.ReadToEndAsync();

        await process.WaitForExitAsync();


        if (process.ExitCode != 0)
        {
            Console.WriteLine(error);
            throw new UnauthorizedAccessException($"AWS SSO login failed with exit code {process.ExitCode}");
        }

        return process.ExitCode;
    }
}