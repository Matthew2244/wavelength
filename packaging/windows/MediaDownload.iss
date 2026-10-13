; Media Download for Windows: the installer (Inno Setup 6).
; Built by build_app.py on Windows:  ISCC /DAppVersion=x.y.z /DSourceDir=dist\Media Download MediaDownload.iss
;
; Installs for the current person only, into their own Programs folder, so it never asks
; for an administrator password. Adds a Start menu entry and an entry in Settings, Apps
; for uninstalling. Uninstalling leaves settings and downloads alone.
; WinSparkle runs this same installer quietly to update (see winsparkle.py).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\Media Download"
#endif

[Setup]
; Never change AppId: it's how Windows knows a new version replaces the old one.
AppId={{9c6c1020-46ac-439b-bfe8-e658c57419b1}
AppName=Media Download
AppVersion={#AppVersion}
AppVerName=Media Download {#AppVersion}
AppPublisher=Matthew Whitaker
AppPublisherURL=https://github.com/Matthew2244/ytdl-accessible
AppSupportURL=https://github.com/Matthew2244/ytdl-accessible/issues
DefaultDirName={localappdata}\Programs\Media Download
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=Media-Download-Setup
SetupIconFile=..\..\assets\icon.ico
UninstallDisplayIcon={app}\Media Download.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Close a running copy before replacing it, and open it again afterwards.
CloseApplications=yes
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Put Media Download on the desktop"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[InstallDelete]
; A new version may drop files the old one had; start clean inside the app folder only.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Media Download"; Filename: "{app}\Media Download.exe"
Name: "{autodesktop}\Media Download"; Filename: "{app}\Media Download.exe"; Tasks: desktopicon

[Run]
; After a normal install: offer to open it. After a quiet update (WinSparkle): open it again.
Filename: "{app}\Media Download.exe"; Description: "Open Media Download now"; Flags: nowait postinstall skipifsilent
Filename: "{app}\Media Download.exe"; Flags: nowait; Check: Relaunch

[Code]
// WinSparkle passes /relaunch=1 when it runs this quietly to update, so the app comes back
// by itself. A quiet install without it (a test machine, an administrator) opens nothing.
function Relaunch(): Boolean;
begin
  Result := WizardSilent() and (ExpandConstant('{param:relaunch|0}') = '1');
end;
