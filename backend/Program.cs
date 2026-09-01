using backend.Services;

DotNetEnv.Env.TraversePath().Load();

var builder = WebApplication.CreateBuilder(args);

var ragServiceUrl = Environment.GetEnvironmentVariable("RAG_SERVICE_URL") ?? "http://localhost:8000";
var frontendUrl = Environment.GetEnvironmentVariable("FRONTEND_URL") ?? "http://localhost:5173";

builder.Services.AddControllers();
builder.Services.AddOpenApi();

builder.Services.AddCors(options =>
{
    options.AddDefaultPolicy(policy =>
        policy.WithOrigins(frontendUrl).AllowAnyHeader().AllowAnyMethod());
});

builder.Services.AddHttpClient<RagService>(client =>
{
    client.BaseAddress = new Uri(ragServiceUrl);
    client.Timeout = TimeSpan.FromSeconds(60);
});

builder.Services.AddHttpClient<SupabaseAuthService>();
builder.Services.AddHttpClient<SupabaseService>();

var app = builder.Build();

if (app.Environment.IsDevelopment())
{
    app.MapOpenApi();
}

app.UseCors();
app.MapControllers();

app.Run();
