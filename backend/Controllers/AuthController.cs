using backend.Services;
using Microsoft.AspNetCore.Mvc;

namespace backend.Controllers;

public record RegisterRequest(string Email, string Password);

[ApiController]
[Route("api/[controller]")]
public class AuthController(SupabaseAuthService auth) : ControllerBase
{
    /// <summary>
    /// Creates a confirmed user (no confirmation email). The React app then
    /// signs in normally with Supabase.
    /// </summary>
    [HttpPost("register")]
    public async Task<IActionResult> Register([FromBody] RegisterRequest request, CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(request.Email) || string.IsNullOrWhiteSpace(request.Password))
        {
            return BadRequest("Email and password are required.");
        }
        if (request.Password.Length < 6)
        {
            return BadRequest("Password must be at least 6 characters.");
        }

        var result = await auth.RegisterAsync(request.Email.Trim(), request.Password, ct);
        return result.Ok ? Ok(new { ok = true }) : BadRequest(result.Error);
    }
}
