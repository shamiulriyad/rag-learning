using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;

namespace backend.Services;

/// <summary>The signed-in user, resolved from a Supabase access token.</summary>
public record AuthUser(string Id, string? Email);

/// <summary>Result of an admin sign-up attempt.</summary>
public record RegisterResult(bool Ok, string? Error);

/// <summary>
/// Talks to Supabase Auth (GoTrue):
///  - validates access tokens via GET /auth/v1/user (no JWT secret needed)
///  - creates users via the admin API, which skips the confirmation email
///    entirely (needs the service_role key).
/// </summary>
public class SupabaseAuthService(HttpClient http)
{
    private readonly string? _url = Environment.GetEnvironmentVariable("SUPABASE_URL");
    private readonly string? _anonKey = Environment.GetEnvironmentVariable("SUPABASE_ANON_KEY");
    private readonly string? _serviceKey = Environment.GetEnvironmentVariable("SUPABASE_SERVICE_ROLE_KEY");

    public bool Enabled => !string.IsNullOrWhiteSpace(_url) && !string.IsNullOrWhiteSpace(_anonKey);
    public bool CanRegister => Enabled && !string.IsNullOrWhiteSpace(_serviceKey);

    /// <summary>Returns the user for a valid token, or null if the token is missing/invalid.</summary>
    public async Task<AuthUser?> GetUserAsync(string? accessToken, CancellationToken ct)
    {
        if (!Enabled || string.IsNullOrWhiteSpace(accessToken))
        {
            return null;
        }

        try
        {
            var request = new HttpRequestMessage(HttpMethod.Get, $"{_url}/auth/v1/user");
            request.Headers.Add("apikey", _anonKey);
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", accessToken);

            var response = await http.SendAsync(request, ct);
            if (!response.IsSuccessStatusCode)
            {
                return null;
            }

            using var json = JsonDocument.Parse(await response.Content.ReadAsStringAsync(ct));
            var root = json.RootElement;
            var id = root.GetProperty("id").GetString();
            if (string.IsNullOrEmpty(id))
            {
                return null;
            }

            var email = root.TryGetProperty("email", out var e) ? e.GetString() : null;
            return new AuthUser(id, email);
        }
        catch
        {
            return null;
        }
    }

    /// <summary>
    /// Creates an already-confirmed user. No email is sent, so this is not
    /// affected by Supabase's email rate limit.
    /// </summary>
    public async Task<RegisterResult> RegisterAsync(string email, string password, CancellationToken ct)
    {
        if (!CanRegister)
        {
            return new RegisterResult(false, "Sign-up is not configured (missing SUPABASE_SERVICE_ROLE_KEY).");
        }

        try
        {
            var request = new HttpRequestMessage(HttpMethod.Post, $"{_url}/auth/v1/admin/users")
            {
                Content = JsonContent.Create(new
                {
                    email,
                    password,
                    email_confirm = true,
                }),
            };
            request.Headers.Add("apikey", _serviceKey);
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _serviceKey);

            var response = await http.SendAsync(request, ct);
            if (response.IsSuccessStatusCode)
            {
                return new RegisterResult(true, null);
            }

            var body = await response.Content.ReadAsStringAsync(ct);
            var message = TryReadError(body) ?? $"Sign-up failed ({(int)response.StatusCode}).";
            return new RegisterResult(false, message);
        }
        catch
        {
            return new RegisterResult(false, "Could not reach the auth service.");
        }
    }

    private static string? TryReadError(string body)
    {
        try
        {
            using var json = JsonDocument.Parse(body);
            foreach (var name in new[] { "msg", "message", "error_description", "error" })
            {
                if (json.RootElement.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String)
                {
                    return v.GetString();
                }
            }
        }
        catch
        {
            // fall through
        }
        return null;
    }
}
