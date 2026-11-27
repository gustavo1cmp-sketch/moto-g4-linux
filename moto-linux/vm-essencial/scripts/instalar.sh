#!/bin/bash
# Gera a imagem do postmarketOS para o Moto G4 (nada vai para o celular).
export PATH=$HOME/.local/bin:$PATH
[ -s ~/senha-pmos.txt ] || { tr -dc a-z0-9 < /dev/urandom | head -c 12 > ~/senha-pmos.txt; chmod 600 ~/senha-pmos.txt; }
{ date; pmbootstrap -y install --password "$(cat ~/senha-pmos.txt)"; echo "SAIDA_INSTALL=$?"; date; } > ~/install.log 2>&1
