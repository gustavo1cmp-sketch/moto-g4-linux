#!/bin/bash
export PATH=$HOME/.local/bin:$PATH
cd ~
{ date
  pmbootstrap shutdown; sudo losetup -D
  pmbootstrap checksum linux-motorola-athene device-motorola-athene &&
  pmbootstrap -y build --force linux-motorola-athene device-motorola-athene &&
  pmbootstrap -y install --password "$(cat ~/senha-pmos.txt)" &&
  pmbootstrap export
  echo "SAIDA=$?"; date; } > ~/recompilar.log 2>&1
