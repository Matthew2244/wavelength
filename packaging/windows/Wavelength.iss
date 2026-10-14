; Wavelength for Windows: the installer (Inno Setup 6).
; Built by build_app.py on Windows:  ISCC /DAppVersion=x.y.z /DSourceDir=dist\Wavelength Wavelength.iss
;
; Installs for the current person only, into their own Programs folder, so it never asks
; for an administrator password. Adds a Start menu entry and an entry in Settings, Apps
; for uninstalling. Uninstalling leaves settings and downloads alone.
; WinSparkle runs this same installer quietly to update (see winsparkle.py).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\Wavelength"
#endif

[Setup]
; Never change AppId: it's how Windows knows a new version replaces the old one.
AppId={{9c6c1020-46ac-439b-bfe8-e658c57419b1}
AppName=Wavelength
AppVersion={#AppVersion}
AppVerName=Wavelength {#AppVersion}
AppPublisher=Matthew Whitaker
AppPublisherURL=https://github.com/Matthew2244/wavelength
AppSupportURL=https://github.com/Matthew2244/wavelength/issues
DefaultDirName={localappdata}\Programs\Wavelength
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=Wavelength-Setup
SetupIconFile=..\..\assets\icon.ico
UninstallDisplayIcon={app}\Wavelength.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Close a running copy before replacing it, and open it again afterwards.
CloseApplications=yes
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Put Wavelength on the desktop"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[InstallDelete]
; A new version may drop files the old one had; start clean inside the app folder only.
Type: filesandordirs; Name: "{app}\_internal"
; The app was called Media Download until 3.0: an update over it removes the old program and its
; shortcuts, so nobody is left with two of them.
Type: files; Name: "{app}\Media Download.exe"
Type: files; Name: "{autoprograms}\Media Download.lnk"
Type: files; Name: "{autodesktop}\Media Download.lnk"

[Icons]
Name: "{autoprograms}\Wavelength"; Filename: "{app}\Wavelength.exe"
Name: "{autodesktop}\Wavelength"; Filename: "{app}\Wavelength.exe"; Tasks: desktopicon

[Run]
; After a normal install: offer to open it. After a quiet update (WinSparkle): open it again.
Filename: "{app}\Wavelength.exe"; Description: "Open Wavelength now"; Flags: nowait postinstall skipifsilent
Filename: "{app}\Wavelength.exe"; Flags: nowait; Check: Relaunch

[Code]
// WinSparkle passes /relaunch=1 when it runs this quietly to update, so the app comes back
// by itself. A quiet install without it (a test machine, an administrator) opens nothing.
function Relaunch(): Boolean;
begin
  Result := WizardSilent() and (ExpandConstant('{param:relaunch|0}') = '1');
end;
