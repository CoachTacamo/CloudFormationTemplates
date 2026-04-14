using AILibraries.Storage.Models;
using Microsoft.Extensions.Options;

namespace ImportDocuments;
internal class SimpleS3Options : IOptions<S3StorageOptions>
{
    public S3StorageOptions Value { get; }
    
    public SimpleS3Options(S3StorageOptions value)
    {
        Value = value;
    }
}
