#!/bin/sh
# Limite de carga do Moto G4 Plus. Fica em /data/adb/service.d/ (o Magisk executa no boot).
PARAR=60  # para de carregar a partir daqui
VOLTAR=55 # volta a carregar daqui para baixo
NO=${NO:-/sys/class/power_supply/battery}
CHAVE="$NO/battery_charging_enabled" # o celular segue alimentado pelo USB

ajustar() {
  c=$(cat "$NO/capacity" 2>/dev/null)
  if [ -z "$c" ]; then
    quer=1 # sem leitura, deixa o aparelho no comportamento normal
  elif [ "$c" -ge "$PARAR" ]; then
    quer=0
  elif [ "$c" -le "$VOLTAR" ]; then
    quer=1
  else
    quer=$(cat "$CHAVE")
  fi
  # O boot pode religar a carga com a chave ainda em 0, e regravar 0 não surte efeito.
  if [ "$quer" = 0 ] && [ "$(cat "$NO/status" 2>/dev/null)" = Charging ]; then
    echo 1 > "$CHAVE"
    sleep 2
  fi
  echo "$quer" > "$CHAVE"
}

if [ "$1" = uma-vez ]; then
  ajustar
  exit
fi

while true; do
  ajustar
  sleep 60
done
