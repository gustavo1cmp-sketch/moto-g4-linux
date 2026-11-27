#!/bin/bash
# Compila o kernel do Moto G4 e registra o resultado.
export PATH=$HOME/.local/bin:$PATH
cd ~
{ date; pmbootstrap -y build linux-motorola-athene; echo "SAIDA_KERNEL=$?"; date; } > ~/kernel.log 2>&1
