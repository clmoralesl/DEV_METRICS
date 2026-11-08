param(
  [Parameter(Mandatory = $true)][string]$Issue,
  [string]$Repo = 'clmoralesl/DEV_METRICS'
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$raiz = Split-Path $PSScriptRoot -Parent
Set-Location $raiz
$carpeta = Join-Path $raiz 'notas_equipo\arranque'
New-Item -ItemType Directory -Force $carpeta | Out-Null

function Quitar-Acentos([string]$texto) {
  $n = $texto.Normalize([Text.NormalizationForm]::FormD)
  $sb = New-Object Text.StringBuilder
  foreach ($c in $n.ToCharArray()) {
    if ([Globalization.CharUnicodeInfo]::GetUnicodeCategory($c) -ne 'NonSpacingMark') { [void]$sb.Append($c) }
  }
  $sb.ToString()
}

function Tipo-Rama($etiquetas) {
  if ($etiquetas -contains 'infraestructura') { return 'infra' }
  if ($etiquetas -contains 'documentation') { return 'docs' }
  if ($etiquetas -contains 'pruebas') { return 'test' }
  return 'feat'
}

git fetch origin --quiet 2>$null

foreach ($n in ($Issue -split '[,\s]+' | Where-Object { $_ } | ForEach-Object { [int]$_ })) {
  $json = gh issue view $n -R $Repo --json title,body,labels,milestone,state | ConvertFrom-Json
  if (-not $json) { Write-Output "Issue ${n}: no se pudo leer"; continue }
  $etiquetas = @($json.labels | ForEach-Object { $_.name })
  $existente = @(git branch --list "*-issue-$n" | ForEach-Object { $_.Trim('* ').Trim() })
  if ($existente.Count -gt 0) {
    $rama = $existente[0]
    $estadoRama = 'existente'
  } else {
    $slug = (Quitar-Acentos $json.title).ToLower() -replace '[^a-z0-9]+', '-'
    $slug = $slug.Trim('-')
    if ($slug.Length -gt 50) { $slug = $slug.Substring(0, 50).Trim('-') }
    $rama = "$(Tipo-Rama $etiquetas)/$slug-issue-$n"
    $base = if (git rev-parse --verify --quiet origin/main) { 'origin/main' } else { 'main' }
    git branch $rama $base
    $estadoRama = "creada desde $base"
  }

  $hito = if ($json.milestone) { $json.milestone.title } else { 'sin hito' }
  $arranque = @(
    "# Arranque del issue $n : $($json.title)",
    '',
    "Hito: $hito. Estado en GitHub: $($json.state). Etiquetas: $($etiquetas -join ', ').",
    "Rama: $rama ($estadoRama). Cambiar con: git switch $rama",
    "Conversacion nueva para este issue. Leer solo: CLAUDE.md, ESTADO.md y este archivo.",
    '',
    '## Issue',
    '',
    $json.body,
    '',
    '## Ciclo',
    '',
    'Ver documentacion/fases.md. Al terminar: bitacora en notas_equipo, ESTADO.md y preparar los siguientes issues con scripts/preparar-issue.ps1.'
  )
  $destino = Join-Path $carpeta "issue_$n.md"
  $arranque | Set-Content -Encoding UTF8 $destino
  Write-Output "Issue ${n}: rama $rama ($estadoRama); arranque en notas_equipo/arranque/issue_$n.md"
}
