@echo off
rem Liga a maquina virtual de compilacao e abre um terminal nela.
"%ProgramFiles%\Oracle\VirtualBox\VBoxManage.exe" list runningvms | find "pmos-build" >nul || "%ProgramFiles%\Oracle\VirtualBox\VBoxManage.exe" startvm pmos-build --type headless
echo Aguardando a maquina virtual...
:espera
ssh -i "%USERPROFILE%\.ssh\pmos_vm" -p 2200 -o BatchMode=yes -o ConnectTimeout=5 -o UserKnownHostsFile="%USERPROFILE%\.ssh\known_hosts_pmos" dev@127.0.0.1 true 2>nul || (timeout /t 3 >nul & goto espera)
ssh -i "%USERPROFILE%\.ssh\pmos_vm" -p 2200 -o UserKnownHostsFile="%USERPROFILE%\.ssh\known_hosts_pmos" dev@127.0.0.1