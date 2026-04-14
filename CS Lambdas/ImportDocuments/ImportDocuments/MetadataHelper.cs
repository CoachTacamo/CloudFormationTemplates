namespace ImportDocuments;

internal static class MetadataHelper
{
    public static IReadOnlyDictionary<string, string> ConvertMetadata(IReadOnlyDictionary<string, object>? fileMetadata)
    {
        Dictionary<string, string> metadata = new();
        
        if (fileMetadata is null)
        {
            return metadata;
        }
        foreach ((string key, object value) in fileMetadata)
        {
            metadata.Add(key, value?.ToString() ?? "");
        }

        return metadata;
    }
}
