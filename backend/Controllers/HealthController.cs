using backend.Services;
using Microsoft.AspNetCore.Mvc;

namespace backend.Controllers;

[ApiController]
[Route("api/[controller]")]
public class HealthController(RagService rag, SupabaseAuthService auth, SupabaseService supabase) : ControllerBase
{
    [HttpGet]
    public async Task<IActionResult> Get(CancellationToken ct)
    {
        return Ok(new
        {
            status = "ok",
            ragService = await rag.IsHealthyAsync(ct) ? "up" : "down",
            supabase = supabase.Enabled ? "configured" : "disabled",
            signup = auth.CanRegister ? "admin (no email)" : "disabled",
        });
    }
}
