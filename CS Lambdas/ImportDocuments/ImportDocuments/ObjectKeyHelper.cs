using AILibraries.Storage.Models;

namespace ImportDocuments;

internal static class ObjectKeyHelper
{
    private static IEnumerable<string> _sortedDocuments = [ "POL", "PRO", "MSM", "WI", "MAA", "SPS", "SSD", "STM" ];

    public static S3ObjectId GetSortObjectKey(string bucket, string objectName)
    {
        string key = "";
        foreach (string docType in _sortedDocuments)
        {
            if (objectName.StartsWith(docType))
            {
                key = Path.Combine(docType, objectName);
                break;
            }
        }

        if (string.IsNullOrEmpty(key))
        {
            key = Path.Combine("Unknown", objectName);
        }

        return new(bucket, key);
    }

}
