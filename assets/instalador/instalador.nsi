Unicode true
!define APP "SistContiffy"
!define EXE "SistContiffy.exe"
!define VER "1.0.0"
!define UNKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\SistemaContableIffyware"

Name "${APP}"
OutFile "Instalador_SistContiffy.exe"
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\Programs\SistemaContableIffyware"
InstallDirRegKey HKCU "Software\SistemaContableIffyware" "Dir"
SetCompressor /SOLID lzma
BrandingText "Iffyware Systems"

!include "MUI2.nsh"
!define MUI_ICON "icon.ico"
!define MUI_UNICON "icon.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\${EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Abrir ${APP} ahora"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Spanish"

VIProductVersion "1.0.0.0"
VIAddVersionKey /LANG=${LANG_SPANISH} "ProductName" "${APP}"
VIAddVersionKey /LANG=${LANG_SPANISH} "CompanyName" "Iffyware Systems"
VIAddVersionKey /LANG=${LANG_SPANISH} "FileDescription" "Instalador de ${APP}"
VIAddVersionKey /LANG=${LANG_SPANISH} "FileVersion" "${VER}"

Section "Instalar"
  SetOutPath "$INSTDIR"
  ; Solo se copia el programa. contabilidad.db NUNCA se toca: si ya existe, queda igual.
  Delete "$INSTDIR\SistemaContableIffyware.exe"
  Delete "$DESKTOP\Sistema Contable Iffyware.lnk"
  Delete "$SMPROGRAMS\Sistema Contable Iffyware\Sistema Contable Iffyware.lnk"
  Delete "$SMPROGRAMS\Sistema Contable Iffyware\Desinstalar.lnk"
  RMDir "$SMPROGRAMS\Sistema Contable Iffyware"
  File "${EXE}"
  File "icon.ico"
  WriteUninstaller "$INSTDIR\Desinstalar.exe"

  CreateDirectory "$SMPROGRAMS\${APP}"
  CreateShortcut "$SMPROGRAMS\${APP}\${APP}.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\icon.ico"
  CreateShortcut "$SMPROGRAMS\${APP}\Desinstalar.lnk" "$INSTDIR\Desinstalar.exe"
  CreateShortcut "$DESKTOP\${APP}.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\icon.ico"

  WriteRegStr HKCU "Software\SistemaContableIffyware" "Dir" "$INSTDIR"
  WriteRegStr HKCU "${UNKEY}" "DisplayName" "${APP}"
  WriteRegStr HKCU "${UNKEY}" "DisplayVersion" "${VER}"
  WriteRegStr HKCU "${UNKEY}" "Publisher" "Iffyware Systems"
  WriteRegStr HKCU "${UNKEY}" "DisplayIcon" "$INSTDIR\icon.ico"
  WriteRegStr HKCU "${UNKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNKEY}" "UninstallString" '"$INSTDIR\Desinstalar.exe"'
  WriteRegDWORD HKCU "${UNKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNKEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  Delete "$INSTDIR\${EXE}"
  Delete "$INSTDIR\icon.ico"
  Delete "$INSTDIR\Desinstalar.exe"
  Delete "$DESKTOP\${APP}.lnk"
  Delete "$SMPROGRAMS\${APP}\${APP}.lnk"
  Delete "$SMPROGRAMS\${APP}\Desinstalar.lnk"
  RMDir "$SMPROGRAMS\${APP}"
  DeleteRegKey HKCU "${UNKEY}"
  DeleteRegKey HKCU "Software\SistemaContableIffyware"
  ; contabilidad.db y los respaldos se conservan a propósito. RMDir solo borra la carpeta si quedó vacía.
  RMDir "$INSTDIR"
SectionEnd
