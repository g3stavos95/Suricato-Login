# autologin_setup.ps1
# ======================================================================================
# Suricato AutoLogin (F12) - Windows 10/11
# Versão: 1.0
# ======================================================================================
# Objetivo:
#   Automatizar o setup do Suricato AutoLogin no Windows:
#     1) Detectar um Python REAL (python.exe) funcional
#     2) Garantir pip
#     3) Instalar dependências com pip --user
#     4) Converter PNG -> ICO (para atalhos do Windows)
#     5) Buildar autologin.exe com PyInstaller (onefile + noconsole) embutindo autologin.png
#     6) Criar atalhos no Desktop e no Menu Iniciar
#
# Por que este script é “robusto”:
#   - Nunca executa python.exe sem argumentos (isso abriria REPL e “travaria”)
#   - Nunca usa py.exe como runtime (py.exe é só para descobrir o python.exe real)
#   - pip pode escrever WARNING em stderr mesmo com sucesso: aqui isso NÃO quebra o setup
#   - Evita bug clássico: Join-Path com vírgula (ChildPath vira Object[] e explode)
# ======================================================================================

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# -------------------------------
# Versão
# -------------------------------
$SCRIPT_VERSION = "1.0"

# -------------------------------
# Encoding (evita caracteres quebrados no log/console)
# -------------------------------
try {
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}

# -------------------------------
# Configuração do App / Pastas
# -------------------------------
$APP_NAME = "Suricato AutoLogin (F12)"
$APP_SLUG = "SuricatoAutoLogin"

# Pasta base do setup (por usuário)
$ROOT_DIR = Join-Path $env:LOCALAPPDATA $APP_SLUG
$WORK_DIR = Join-Path $ROOT_DIR "work"
$DIST_DIR = Join-Path $ROOT_DIR "dist"
$LOG_DIR  = Join-Path $ROOT_DIR "logs"

# Log único por execução
$LOG_FILE = Join-Path $LOG_DIR ("setup_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

# Saída do build
$EXE_OUT = Join-Path $DIST_DIR "autologin.exe"

# Atalhos
$DESKTOP_DIR  = [Environment]::GetFolderPath("Desktop")
$STARTMENU_DIR = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$SHORTCUT_DESKTOP = Join-Path $DESKTOP_DIR "$APP_NAME.lnk"
$SHORTCUT_START   = Join-Path $STARTMENU_DIR "$APP_NAME.lnk"

# Ícone final .ico (gerado a partir do PNG selecionado)
$ICO_OUT = Join-Path $ROOT_DIR "autologin.ico"

# -------------------------------
# Criação de diretórios
# -------------------------------
function New-Dirs {
  New-Item -ItemType Directory -Force -Path $ROOT_DIR, $WORK_DIR, $DIST_DIR, $LOG_DIR | Out-Null
}

# -------------------------------
# Logging / Erros
# -------------------------------
function Log([string]$Msg) {
  New-Dirs
  $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Msg
  $line | Tee-Object -FilePath $LOG_FILE -Append | Out-Host
}

function Fail([string]$Msg) {
  Log "ERROR: $Msg"
  try {
    Add-Type -AssemblyName System.Windows.Forms | Out-Null
    [System.Windows.Forms.MessageBox]::Show("$Msg`n`nLog: $LOG_FILE", "AutoLogin Setup", "OK", "Error") | Out-Null
  } catch {}
  throw $Msg
}

function Info([string]$Msg) {
  Log "INFO: $Msg"
  try {
    Add-Type -AssemblyName System.Windows.Forms | Out-Null
    [System.Windows.Forms.MessageBox]::Show($Msg, "AutoLogin Setup", "OK", "Information") | Out-Null
  } catch {
    Write-Host $Msg
  }
}

function Ask([string]$Msg) {
  Log "QUESTION: $Msg"
  try {
    Add-Type -AssemblyName System.Windows.Forms | Out-Null
    $res = [System.Windows.Forms.MessageBox]::Show($Msg, "AutoLogin Setup", "YesNo", "Question")
    return ($res -eq [System.Windows.Forms.DialogResult]::Yes)
  } catch {
    $ans = Read-Host "$Msg (S/N)"
    return ($ans -match '^[sS]$')
  }
}

# -------------------------------
# Picker de arquivos (GUI)
# -------------------------------
function Pick-File([string]$Title, [string]$Filter) {
  Add-Type -AssemblyName System.Windows.Forms | Out-Null
  $dlg = New-Object System.Windows.Forms.OpenFileDialog
  $dlg.Title = $Title
  $dlg.Filter = $Filter
  $dlg.Multiselect = $false
  $dlg.CheckFileExists = $true
  $dlg.CheckPathExists = $true
  if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    return $dlg.FileName
  }
  return $null
}

# ======================================================================================
# Runner robusto (corrige “pip WARNING quebra o script”)
# ======================================================================================
function Run {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$File,

    # Tudo após o $File entra aqui, sem ambiguidade
    [Parameter(ValueFromRemainingArguments=$true)]
    [object[]]$Args
  )

  if ($null -eq $Args) { $Args = @() }

  # Sanitiza args (remove nulos e strings vazias)
  $cleanArgs = @()
  foreach ($a in $Args) {
    if ($null -eq $a) { continue }
    $s = [string]$a
    if ([string]::IsNullOrWhiteSpace($s)) { continue }
    $cleanArgs += $s
  }

  Log ("RUN: {0} {1}" -f $File, ($cleanArgs -join " "))

  # Guardrail: python.exe sem args abre REPL e “trava”
  if ($File -match '\\python\.exe$' -and $cleanArgs.Count -eq 0) {
    Fail "Guardrail: tentativa de executar python.exe sem argumentos (isso abre modo interativo e trava)."
  }

  # Guardrail: py.exe nunca deve ser runtime do setup
  if ($File -match '\\py\.exe$') {
    Fail "Guardrail: py.exe não deve ser executado via Run() (somente para descobrir python.exe real)."
  }

  # pip e outras ferramentas escrevem WARNING em stderr mesmo com sucesso.
  # PowerShell pode tratar stderr como erro não-terminante; aqui neutralizamos isso,
  # e falhamos SOMENTE se ExitCode != 0.
  $oldEAP = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    $out = & $File @cleanArgs 2>&1
    $exit = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $oldEAP
  }

  if ($out) {
    ($out | Out-String).TrimEnd() | Tee-Object -FilePath $LOG_FILE -Append | Out-Null
  }

  if ($exit -ne 0) {
    Fail "Falha executando comando (exit $exit). Veja o log: $LOG_FILE"
  }
}

# ======================================================================================
# Resolução do Python REAL (sem bug de Join-Path com arrays)
# ======================================================================================
$script:PYTHON_EXE = $null

function Test-RealPython([string]$PythonExe) {
  try {
    # Validação segura: -c sempre termina
    & $PythonExe -c "import sys; print(sys.version.split()[0])" > $null 2>&1
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  }
}

function Resolve-PythonExe {
  # 1) python no PATH (evita alias WindowsApps)
  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if ($cmd -and $cmd.Source -and ($cmd.Source -notmatch '\\WindowsApps\\python\.exe$')) {
    if (Test-RealPython $cmd.Source) { return $cmd.Source }
  }

  # 2) Buscar em locais comuns sem usar Join-Path com vírgula (isso gera Object[])
  $candidatePaths = @()

  # LocalAppData - python.org installer tradicional
  $candidatePaths += Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"
  $candidatePaths += Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
  $candidatePaths += Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"
  $candidatePaths += Join-Path $env:LOCALAPPDATA "Programs\Python\Python314\python.exe"

  # Microsoft Store package (ex.: pythoncore-3.14-64)
  $candidatePaths += Join-Path $env:LOCALAPPDATA "Python\pythoncore-3.11-64\python.exe"
  $candidatePaths += Join-Path $env:LOCALAPPDATA "Python\pythoncore-3.12-64\python.exe"
  $candidatePaths += Join-Path $env:LOCALAPPDATA "Python\pythoncore-3.13-64\python.exe"
  $candidatePaths += Join-Path $env:LOCALAPPDATA "Python\pythoncore-3.14-64\python.exe"

  # Program Files (instalações “machine-wide”)
  $candidatePaths += "C:\Program Files\Python311\python.exe"
  $candidatePaths += "C:\Program Files\Python312\python.exe"
  $candidatePaths += "C:\Program Files\Python313\python.exe"
  $candidatePaths += "C:\Program Files\Python314\python.exe"
  $candidatePaths += "C:\Program Files (x86)\Python311\python.exe"

  foreach ($p in $candidatePaths | Select-Object -Unique) {
    if (Test-Path $p) {
      if (Test-RealPython $p) { return $p }
    }
  }

  # 3) Fallback: py launcher (APENAS para descobrir sys.executable)
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py -and $py.Source) {
    try {
      $real = & $py.Source -3 -c "import sys; print(sys.executable)" 2>&1
      if ($LASTEXITCODE -eq 0) {
        $realPath = ($real | Out-String).Trim()
        if ($realPath -and (Test-Path $realPath) -and (Test-RealPython $realPath)) {
          return $realPath
        }
      }
    } catch {}
  }

  return $null
}

function Ensure-Python {
  $exe = Resolve-PythonExe
  if (-not $exe) {
    Fail "Python 3 não encontrado. Instale o Python e tente novamente."
  }
  $script:PYTHON_EXE = $exe
  Run $script:PYTHON_EXE -c "import sys; print('python-ok', sys.version.split()[0], sys.executable)"
  Log "Python real selecionado: $script:PYTHON_EXE"
}

# ======================================================================================
# pip + dependências
# ======================================================================================
function Ensure-Pip {
  Run $script:PYTHON_EXE -m pip --version
}

function Ensure-Deps {
  # Dependências do app + build
  $pkgs = @("pyautogui","pynput","cryptography","pystray","pillow","pyinstaller")
  Run $script:PYTHON_EXE -m pip install --user --upgrade pip
  Run $script:PYTHON_EXE -m pip install --user --upgrade @pkgs
  Run $script:PYTHON_EXE -c "import PyInstaller, PIL; print('deps ok')"
}

# ======================================================================================
# PNG -> ICO (Pillow)
# ======================================================================================
function Convert-PngToIco([string]$PngPath, [string]$IcoPath) {
  $code = @"
from PIL import Image
img = Image.open(r'''$PngPath''').convert('RGBA')
sizes = [(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)]
img.save(r'''$IcoPath''', format='ICO', sizes=sizes)
print("ico-ok", r'''$IcoPath''')
"@
  $tmp = Join-Path $WORK_DIR "make_ico.py"
  Set-Content -Path $tmp -Value $code -Encoding UTF8
  Run $script:PYTHON_EXE $tmp
}

# ======================================================================================
# Build com PyInstaller
# ======================================================================================
function Build-Exe([string]$PyPath, [string]$IconPngPath) {
  # Limpa pasta de trabalho para evitar lixo antigo
  if (Test-Path $WORK_DIR) { Remove-Item $WORK_DIR -Recurse -Force -ErrorAction SilentlyContinue }
  if (Test-Path $DIST_DIR) { Remove-Item $DIST_DIR -Recurse -Force -ErrorAction SilentlyContinue }
  New-Dirs
  New-Item -ItemType Directory -Force -Path $WORK_DIR | Out-Null

  # Copia os arquivos para WORK_DIR (padroniza caminhos)
  Copy-Item -Force $PyPath      (Join-Path $WORK_DIR "autologin.py")
  Copy-Item -Force $IconPngPath (Join-Path $WORK_DIR "autologin.png")

  Push-Location $WORK_DIR
  try {
    # No Windows o separador do --add-data é ";"
    Run $script:PYTHON_EXE -m PyInstaller `
      --onefile `
      --noconsole `
      --clean `
      --name autologin `
      --add-data "autologin.png;." `
      "autologin.py"
  } finally {
    Pop-Location
  }

  $built = Join-Path $WORK_DIR "dist\autologin.exe"
  if (-not (Test-Path $built)) {
    Fail "Build terminou, mas não encontrei o executável em: $built"
  }

  New-Item -ItemType Directory -Force -Path $DIST_DIR | Out-Null
  Copy-Item -Force $built $EXE_OUT
  Log "Executável gerado em: $EXE_OUT"
}

# ======================================================================================
# Atalhos (.lnk)
# ======================================================================================
function Create-Shortcut([string]$ShortcutPath, [string]$TargetPath, [string]$IconIcoPath) {
  $wsh = New-Object -ComObject WScript.Shell
  $s = $wsh.CreateShortcut($ShortcutPath)
  $s.TargetPath = $TargetPath
  $s.WorkingDirectory = Split-Path $TargetPath -Parent
  if (Test-Path $IconIcoPath) { $s.IconLocation = $IconIcoPath }
  $s.Save()
}

# ======================================================================================
# MAIN
# ======================================================================================
function Main {
  New-Dirs
  Log "=== Início Setup Windows: $APP_NAME | v$SCRIPT_VERSION ==="
  Log "Script: $PSCommandPath"
  Log "Log: $LOG_FILE"

  Write-Progress -Activity "AutoLogin Setup" -Status "Verificando Python" -PercentComplete 5
  Ensure-Python

  Write-Progress -Activity "AutoLogin Setup" -Status "Verificando pip" -PercentComplete 12
  Ensure-Pip

  Write-Progress -Activity "AutoLogin Setup" -Status "Selecione o autologin.py" -PercentComplete 20
  $py = Pick-File "Selecione o autologin.py" "Python (*.py)|*.py|Todos (*.*)|*.*"
  if (-not $py) { Log "Cancelado (py)"; return }
  if (-not (Test-Path $py)) { Fail "Arquivo não encontrado: $py" }

  Write-Progress -Activity "AutoLogin Setup" -Status "Selecione o ícone PNG" -PercentComplete 25
  $png = Pick-File "Selecione o ícone (PNG)" "PNG (*.png)|*.png|Todos (*.*)|*.*"
  if (-not $png) { Log "Cancelado (png)"; return }
  if (-not (Test-Path $png)) { Fail "Ícone não encontrado: $png" }

  Write-Progress -Activity "AutoLogin Setup" -Status "Instalando dependências Python" -PercentComplete 45
  Ensure-Deps

  Write-Progress -Activity "AutoLogin Setup" -Status "Gerando ícone ICO" -PercentComplete 60
  Convert-PngToIco -PngPath $png -IcoPath $ICO_OUT

  Write-Progress -Activity "AutoLogin Setup" -Status "Buildando executável (PyInstaller)" -PercentComplete 80
  Build-Exe -PyPath $py -IconPngPath $png

  Write-Progress -Activity "AutoLogin Setup" -Status "Criando atalhos" -PercentComplete 92
  Create-Shortcut -ShortcutPath $SHORTCUT_DESKTOP -TargetPath $EXE_OUT -IconIcoPath $ICO_OUT
  Create-Shortcut -ShortcutPath $SHORTCUT_START   -TargetPath $EXE_OUT -IconIcoPath $ICO_OUT

  Write-Progress -Activity "AutoLogin Setup" -Completed -Status "Concluído"

  Info @"
Instalação concluída (v$SCRIPT_VERSION)!

Executável:
$EXE_OUT

Atalhos:
- Desktop: $SHORTCUT_DESKTOP
- Menu Iniciar: $SHORTCUT_START

Log:
$LOG_FILE
"@

  if (Ask "Deseja iniciar agora?") {
    Start-Process -FilePath $EXE_OUT | Out-Null
  }

  Log "=== Fim ==="
}

try {
  Main
} catch {
  Fail $_.Exception.Message
}
