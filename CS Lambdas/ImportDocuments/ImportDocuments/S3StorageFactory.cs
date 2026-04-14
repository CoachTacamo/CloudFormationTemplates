using AILibraries.Storage.Abstractions;
using AILibraries.Storage.Implementations;
using AILibraries.Storage.Models;
using Amazon.S3;
using ImportDocuments;
using Microsoft.Extensions.Logging;

public static class S3StorageFactory
{
    public static IS3Storage Create(
        S3StorageOptions options,
        IAmazonS3 s3Client,
        ILogger<S3Storage> logger)
    {
        SimpleS3Options simpleOptions = new(options);

        return new S3Storage(s3Client, simpleOptions, logger);
    }
}
