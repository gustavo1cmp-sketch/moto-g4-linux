#!/bin/sh
# Testa limite_carga.sh com uma pasta falsa no lugar do /sys. Uso: sh test_limite.sh
cd "$(dirname "$0")" || exit 1
NO=$(mktemp -d)
export NO
trap 'rm -rf "$NO"' EXIT
falhas=0

caso() { # capacidade estado_anterior esperado
  echo "$1" > "$NO/capacity"
  echo "$2" > "$NO/battery_charging_enabled"
  sh limite_carga.sh uma-vez
  obtido=$(cat "$NO/battery_charging_enabled")
  [ "$obtido" = "$3" ] || { echo "FALHOU: $1% antes=$2 esperado=$3 obtido=$obtido"; falhas=$((falhas + 1)); }
}

# "sleep" falso: anota o valor da chave durante a espera, para ver se ela foi religada.
mkdir "$NO/bin"
printf '#!/bin/sh\ncat "$NO/battery_charging_enabled" >> "$NO/historico"\n' > "$NO/bin/sleep"
chmod +x "$NO/bin/sleep"
PATH="$NO/bin:$PATH"

reaplica() { # capacidade estado_anterior status religou(sim/nao) esperado
  echo "$3" > "$NO/status"
  rm -f "$NO/historico"
  caso "$1" "$2" "$5"
  religou=nao
  grep -qx 1 "$NO/historico" 2>/dev/null && religou=sim
  [ "$religou" = "$4" ] || { echo "FALHOU: $1% status=$3 religou=$religou esperado=$4"; falhas=$((falhas + 1)); }
}

reaplica 65 0 Charging sim 0     # chave em 0 mas o aparelho ignorou: reaplica
reaplica 57 0 Charging sim 0     # idem entre os limites
reaplica 65 0 Discharging nao 0  # parada funcionando: não mexe
reaplica 57 1 Charging nao 1     # carregando de propósito: não mexe
echo Discharging > "$NO/status"

caso 100 1 0   # cheio: para
caso 60 1 0    # no limite: para
caso 59 1 1    # entre os limites: continua carregando
caso 57 0 0    # entre os limites: continua parado
caso 55 0 1    # chegou no piso: volta a carregar
caso 5 0 1     # descarregado: carrega
caso "" 0 1    # leitura falhou: volta ao normal

[ $falhas = 0 ] && echo "OK (11 casos)" || exit 1
