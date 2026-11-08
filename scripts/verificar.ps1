param(
  [string]$Config = (Join-Path $PSScriptRoot 'verificar.config.json')
)

$ErrorActionPreference = 'Continue'
$raiz = Split-Path $PSScriptRoot -Parent
Set-Location $raiz

$venv = Join-Path $raiz '.venv\Scripts'
if (Test-Path $venv) { $env:PATH = "$venv;$env:PATH" }

$cfg = Get-Content $Config -Raw -Encoding UTF8 | ConvertFrom-Json
$tmp = Join-Path $env:TEMP 'devmetrics-verificacion'
New-Item -ItemType Directory -Force $tmp | Out-Null

$resultados = @()
$bloqueo = $false

foreach ($paso in $cfg.pasos) {
  if ($paso.siExiste -and -not (Test-Path (Join-Path $raiz $paso.siExiste))) {
    $resultados += [pscustomobject]@{ Nombre = $paso.nombre; Estado = 'OMITIDO'; Resumen = "no existe $($paso.siExiste)"; Cola = @() }
    continue
  }
  $log = Join-Path $tmp "$($paso.nombre).log"
  $inicio = Get-Date
  cmd /c "$($paso.comando) > `"$log`" 2>&1"
  $codigo = $LASTEXITCODE
  $seg = [math]::Round(((Get-Date) - $inicio).TotalSeconds, 1)
  $lineas = @()
  if (Test-Path $log) { $lineas = @(Get-Content $log -Encoding UTF8 -ErrorAction SilentlyContinue) }
  $ultima = ($lineas | Where-Object { $_.Trim() } | Select-Object -Last 1)
  if (-not $ultima) { $ultima = 'sin salida' }

  if ($codigo -eq 0) {
    $estado = 'OK'; $cola = @()
  } elseif ($lineas -match '.exe: No module named|is not recognized|no se reconoce|command not found') {
    $estado = 'BLOQUEO'; $bloqueo = $true
    $cola = @($lineas | Select-Object -Last 5)
  } else {
    $estado = 'FALLA'
    $cola = @($lineas | Select-Object -Last $cfg.lineasPorFalla)
  }
  $resultados += [pscustomobject]@{ Nombre = $paso.nombre; Estado = $estado; Resumen = "$ultima (${seg}s)"; Cola = $cola }
}

$falla = @($resultados | Where-Object Estado -eq 'FALLA').Count -gt 0
$global = if ($bloqueo) { 'BLOQUEO' } elseif ($falla) { 'ROJO' } else { 'VERDE' }

$salida = @("VERIFICACION: $global", "Fecha: $(Get-Date -Format 'yyyy-MM-dd HH:mm')", '')
foreach ($r in $resultados) {
  $salida += "- $($r.Nombre): $($r.Estado) - $($r.Resumen)"
  if ($r.Cola.Count -gt 0) {
    $salida += '  Detalle (ultimas lineas):'
    $salida += ($r.Cola | ForEach-Object { "    $_" })
  }
}

$destino = Join-Path $raiz '.claude\verificacion.md'
$salida | Set-Content -Encoding UTF8 $destino
$salida | Write-Output

if ($bloqueo) { exit 2 }
if ($falla) { exit 1 }
exit 0
