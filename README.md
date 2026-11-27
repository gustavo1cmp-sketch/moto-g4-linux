# Moto G4 Plus com Linux

Moto G4 Plus (XT1640, codinome **athene**) reaproveitado como painel do PC: o Android foi trocado pelo
**postmarketOS** (kernel 3.10.108), e a tela do celular mostra CPU, GPU, RAM, perfis e a música tocando no PC.

## Pastas

| Pasta | O que tem |
|---|---|
| `painel-pc/` | `painel.py` (roda no Windows: lê o MSI Afterburner e a mídia, manda ao celular), `tela_celular.py` (roda no celular: desenha na tela e lê o toque), testes, `instalar_perfis.ps1` |
| `moto-linux/` | acesso por SSH (`conectar-pmos.cmd`), boot gravado (`pmos-boot-gravado.img`), correções da porta |
| `moto-linux/vm-essencial/` | o necessário para recompilar ou reinstalar; veja o `LEIA-ME.txt` dentro |

## Correções da porta motorola-athene (arquivada no pmaports)

- Câmera e sensor VL53L0 desligados no kernel (travavam o boot); initramfs em gzip.
- `dt.img` no formato Motorola (QCDT 0x103, `dtbtool --force-v3 --motorola 1`), senão o bootloader ignora o boot.
- Patch no `loop` para ignorar `O_DIRECT` (montar o sistema travava).
- Wi-Fi: firmware da partição modem e `wpa_supplicant -Dwext` (o NetworkManager não completa o WPA com o driver prima).
- Som: firmware do ADSP e a rota `QUIN_MI2S_RX` até o amplificador CS35L34; sem dmix (trava neste kernel).
- Rede USB com o Windows sem driver extra: `f_rndis/wceis=1`.

## Fora do repositório

Senha do Wi-Fi (vai só `casa.conf.exemplo`) e os backups do Android, que têm identificadores do aparelho.
