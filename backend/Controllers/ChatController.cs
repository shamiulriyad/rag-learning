using backend.Models;
using backend.Services;
using Microsoft.AspNetCore.Mvc;

namespace backend.Controllers;

[ApiController]
[Route("api/[controller]")]
public class ChatController(RagService rag, SupabaseAuthService auth, SupabaseService supabase) : ControllerBase
{
    /// <summary>Dev switch: when <c>ALLOW_ANONYMOUS=true</c>, /api/chat works without a
    /// Supabase login. Answers still come from the RAG service; chat history is not saved.</summary>
    private static bool AllowAnonymous =>
        string.Equals(Environment.GetEnvironmentVariable("ALLOW_ANONYMOUS"), "true", StringComparison.OrdinalIgnoreCase);

    /// <summary>Ask a question about the English book. Requires a Supabase access token
    /// unless ALLOW_ANONYMOUS is set.</summary>
    [HttpPost]
    public async Task<ActionResult<ChatResponse>> Ask([FromBody] ChatRequest request, CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(request.Question))
        {
            return BadRequest("Question is required.");
        }

        var token = GetBearerToken();
        var user = await auth.GetUserAsync(token, ct);
        if (user is null && !AllowAnonymous)
        {
            return Unauthorized("Sign in to ask a question.");
        }

        var conversationId = string.IsNullOrWhiteSpace(request.ConversationId)
            ? Guid.NewGuid().ToString()
            : request.ConversationId;

        ChatResponse answer;
        try
        {
            answer = await rag.AskAsync(request.Question, conversationId, ct);
        }
        catch (HttpRequestException)
        {
            return StatusCode(StatusCodes.Status503ServiceUnavailable,
                "The RAG service is not reachable. Start it on " +
                (Environment.GetEnvironmentVariable("RAG_SERVICE_URL") ?? "http://localhost:8000") + ".");
        }

        // Persist only for a real signed-in user - the token is what makes the
        // Supabase row-level security policies apply. Anonymous chats are not saved.
        if (user is not null && token is not null)
        {
            await supabase.EnsureConversationAsync(conversationId, user.Id, token, ct);
            await supabase.SaveMessageAsync(conversationId, user.Id, "user", request.Question, token, ct);
            await supabase.SaveMessageAsync(conversationId, user.Id, "assistant", answer.Answer, token, ct);
        }

        return Ok(answer);
    }

    private string? GetBearerToken()
    {
        var header = Request.Headers.Authorization.ToString();
        return header.StartsWith("Bearer ", StringComparison.OrdinalIgnoreCase)
            ? header["Bearer ".Length..].Trim()
            : null;
    }
}
