using System.Net.Http.Headers;
using System.Net.Http.Json;

namespace backend.Services;

/// <summary>
/// Best-effort persistence of conversations and messages to Supabase (PostgREST).
/// Calls are made with the signed-in user's access token so row-level security
/// policies apply. If Supabase is not configured, every call is a no-op.
/// </summary>
public class SupabaseService(HttpClient http)
{
    private readonly string? _url = Environment.GetEnvironmentVariable("SUPABASE_URL");
    private readonly string? _key = Environment.GetEnvironmentVariable("SUPABASE_ANON_KEY");

    public bool Enabled => !string.IsNullOrWhiteSpace(_url) && !string.IsNullOrWhiteSpace(_key);

    /// <summary>Create the conversation row if it does not exist yet (upsert on id).</summary>
    public async Task EnsureConversationAsync(string conversationId, string userId, string accessToken, CancellationToken ct)
    {
        await SendAsync(
            "conversations",
            new { id = conversationId, user_id = userId },
            accessToken,
            "resolution=merge-duplicates,return=minimal",
            ct);
    }

    /// <summary>Insert one row into the <c>messages</c> table.</summary>
    public async Task SaveMessageAsync(string conversationId, string userId, string role, string content, string accessToken, CancellationToken ct)
    {
        await SendAsync(
            "messages",
            new { conversation_id = conversationId, user_id = userId, role, content },
            accessToken,
            "return=minimal",
            ct);
    }

    private async Task SendAsync(string table, object body, string accessToken, string prefer, CancellationToken ct)
    {
        if (!Enabled)
        {
            return;
        }

        try
        {
            var request = new HttpRequestMessage(HttpMethod.Post, $"{_url}/rest/v1/{table}")
            {
                Content = JsonContent.Create(body),
            };
            request.Headers.Add("apikey", _key);
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", accessToken);
            request.Headers.Add("Prefer", prefer);

            await http.SendAsync(request, ct);
        }
        catch
        {
            // Persistence is optional; never break the chat flow because of it.
        }
    }
}
