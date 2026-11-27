@echo off
rem Abre um terminal no Linux do Moto G4 pelo cabo USB.
"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" forward tcp:2222 tcp:2222 >nul || (echo Celular nao encontrado. & pause & exit /b 1)
ssh -i "%USERPROFILE%\.ssh\moto_g4" -o UserKnownHostsFile="%USERPROFILE%\.ssh\known_hosts_moto" -o StrictHostKeyChecking=accept-new -p 2222 root@127.0.0.1 %*
