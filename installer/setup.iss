; Inno Setup script for ASCII Terminal Player.
; Per-user install (no admin rights needed) that copies ascii.exe and adds
; its folder to the current user's PATH, so "ascii" works from any cmd/
; PowerShell/Windows Terminal prompt, in any directory.

#define MyAppName "ASCII Terminal Player"
#define MyAppVersion "1.0.0"
#define MyAppExeName "ascii.exe"

[Setup]
AppId={{B7B6C6B0-3E9B-4B7E-9C7B-ASCIITERMPLAYER}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Ido Cohen
DefaultDirName={localappdata}\Programs\AsciiTerminalPlayer
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=AsciiTerminalPlayer-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "..\dist\ascii.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Code]
const
  EnvironmentKey = 'Environment';

// Standard Inno Setup pattern for editing the current user's PATH:
// read HKCU\Environment\Path, append/remove {app}, then broadcast
// WM_SETTINGCHANGE so newly opened terminals pick it up without a reboot
// (already-open terminals still need to be restarted -- normal Windows
// behavior, not specific to this installer).

procedure EnvAddPath(Path: string);
var
  Paths: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, EnvironmentKey, 'Path', Paths) then
    Paths := '';

  if (Paths <> '') and (Pos(';' + Uppercase(Path) + ';', ';' + Uppercase(Paths) + ';') > 0) then
    exit; // already present

  if (Paths <> '') and (Paths[Length(Paths)] <> ';') then
    Paths := Paths + ';';
  Paths := Paths + Path;

  if RegWriteStringValue(HKEY_CURRENT_USER, EnvironmentKey, 'Path', Paths) then
    Log(Format('Added "%s" to PATH', [Path]))
  else
    Log(Format('Failed to add "%s" to PATH', [Path]));
end;

procedure EnvRemovePath(Path: string);
var
  Paths: string;
  P: Integer;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, EnvironmentKey, 'Path', Paths) then
    exit;

  P := Pos(';' + Uppercase(Path) + ';', ';' + Uppercase(Paths) + ';');
  if P = 0 then
    exit;

  Delete(Paths, P - 1, Length(Path) + 1);
  RegWriteStringValue(HKEY_CURRENT_USER, EnvironmentKey, 'Path', Paths);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    EnvAddPath(ExpandConstant('{app}'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    EnvRemovePath(ExpandConstant('{app}'));
end;
