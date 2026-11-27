# Limpeza do Moto G4 Plus (serial SEU_SERIAL) - 2026-11-26

Só `pm disable-user --user 0` + `am force-stop`. Nada desinstalado, nenhum dado apagado.

## Pacotes desativados nesta limpeza (21)

- com.google.android.googlequicksearchbox (app Google / assistente / voz)
- com.google.android.youtube
- com.google.android.videos
- com.google.android.music
- com.google.android.gm
- com.google.android.apps.photos
- com.google.android.apps.docs
- com.google.android.apps.maps
- com.google.android.apps.tachyon (Duo)
- com.google.android.talk (Hangouts)
- com.google.android.calendar
- com.google.android.deskclock
- com.google.android.calculator
- com.google.android.apps.wallpaper
- com.google.android.feedback
- com.google.android.printservice.recommendation
- com.motorola.bug2go
- com.motorola.brapps
- com.motorola.timeweatherwidget
- com.motorola.fmplayer
- com.motorola.genie (ajuda Motorola)

Os demais pacotes que aparecem em `pm list packages -d` já estavam desativados antes.

## Reverter (Git Bash)

```bash
export MSYS_NO_PATHCONV=1; ADB="$LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe"; S=SEU_SERIAL
G=com.google.android; M=com.motorola
for p in $G.googlequicksearchbox $G.youtube $G.videos $G.music $G.gm $G.apps.photos $G.apps.docs $G.apps.maps $G.apps.tachyon $G.talk $G.calendar $G.deskclock $G.calculator $G.apps.wallpaper $G.feedback $G.printservice.recommendation $M.bug2go $M.brapps $M.timeweatherwidget $M.fmplayer $M.genie; do
  $ADB -s $S shell pm enable $p
done
# restaura o assistente de voz (desativar o app Google esvaziou estes ajustes)
$ADB -s $S shell settings put secure voice_interaction_service com.google.android.googlequicksearchbox/com.google.android.voiceinteraction.GsaVoiceInteractionService
$ADB -s $S shell settings put secure voice_recognition_service com.google.android.googlequicksearchbox/com.google.android.voicesearch.serviceapi.GoogleRecognitionService
```

Widgets removidos da tela inicial (busca Google, hora/clima) podem precisar ser recolocados à mão.
