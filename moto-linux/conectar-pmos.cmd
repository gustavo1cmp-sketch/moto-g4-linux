@echo off
rem Abre um terminal no postmarketOS do celular pelo cabo USB (rede 172.16.42.x).
rem Uso: conectar-pmos.cmd          -> entra como "user"
rem      conectar-pmos.cmd root     -> entra como root
set USUARIO=%1
if "%USUARIO%"=="" set USUARIO=user
ssh -i "%USERPROFILE%\.ssh\moto_g4" -o UserKnownHostsFile="%USERPROFILE%\.ssh\known_hosts_pmos_celular" -o StrictHostKeyChecking=accept-new %USUARIO%@172.16.42.1
