# Cria as tarefas que trocam o perfil do MSI Afterburner sem o aviso de administrador do Windows.
# Rodar uma vez, como administrador. Para remover: Unregister-ScheduledTask -TaskPath '\Painel do PC\' -Confirm:$false
$exe = 'C:\Program Files (x86)\MSI Afterburner\MSIAfterburner.exe'
$usuario = "$env:USERDOMAIN\$env:USERNAME"
foreach ($n in 1..3) {
    Register-ScheduledTask -TaskPath '\Painel do PC\' -TaskName "Afterburner perfil $n" -Force `
        -Action (New-ScheduledTaskAction -Execute $exe -Argument "-Profile$n") `
        -Principal (New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Highest) `
        -Settings (New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 1)) | Out-Null
    "tarefa criada: Afterburner perfil $n"
}
