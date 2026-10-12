$ErrorActionPreference = 'Stop'
$mcpExePath = Join-Path $PSScriptRoot 'MCPaint-MCP.exe'
if (-not (Test-Path $mcpExePath)) {
    throw 'MCPaint-MCP.exe is missing. Extract the entire ZIP first.'
}
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    throw 'Codex CLI was not found. Use docs/mcp-setup.md to configure your MCP client.'
}
& codex mcp add mcpaint -- $mcpExePath
if ($LASTEXITCODE -ne 0) { throw 'Codex MCP registration failed.' }
Write-Host 'MCPaint has been registered. Restart your Codex session.'
