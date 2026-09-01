using System.Net.Http.Json;
using backend.Models;

namespace backend.Services;

/// <summary>Thin client over the Python FastAPI RAG service.</summary>
public class RagService(HttpClient http)
{
    private record RagQuery(string question, int? top_k);
    private record RagSource(int? page, string source, double score);
    private record RagAnswer(string answer, List<RagSource> sources);

    public async Task<ChatResponse> AskAsync(string question, string? conversationId, CancellationToken ct)
    {
        var response = await http.PostAsJsonAsync("/query", new RagQuery(question, null), ct);
        response.EnsureSuccessStatusCode();

        var body = await response.Content.ReadFromJsonAsync<RagAnswer>(ct)
                   ?? new RagAnswer(string.Empty, []);

        var sources = body.sources
            .Select(s => new SourceRef(s.page, s.source, s.score))
            .ToList();

        return new ChatResponse(body.answer, sources, conversationId);
    }

    public async Task<bool> IsHealthyAsync(CancellationToken ct)
    {
        try
        {
            var response = await http.GetAsync("/health", ct);
            return response.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }
}
