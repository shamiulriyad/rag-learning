namespace backend.Models;

/// <summary>Question coming from the React app.</summary>
public record ChatRequest(string Question, string? ConversationId);

/// <summary>A page/section reference returned alongside an answer.</summary>
public record SourceRef(int? Page, string Source, double Score);

/// <summary>Answer returned to the React app.</summary>
public record ChatResponse(string Answer, IReadOnlyList<SourceRef> Sources, string? ConversationId);
