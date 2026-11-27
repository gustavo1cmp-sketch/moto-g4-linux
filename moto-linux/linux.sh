#!/system/bin/sh
# Sobe o Alpine (chroot) e o SSH. Fica em /data/adb/service.d/ (o Magisk executa no boot).
R=/data/linux/alpine
[ -x "$R/bin/busybox" ] || exit 0

montar() { # destino, argumentos do mount
  destino=$1
  shift
  grep -q " $destino " /proc/mounts || mount "$@" "$destino"
}

montar "$R/proc" -t proc proc
montar "$R/sys" -t sysfs sysfs
montar "$R/dev" -o bind /dev
montar "$R/dev/pts" -o bind /dev/pts

# Só em 127.0.0.1 (acesso pelo cabo com "adb forward") e só com chave, sem senha (-s).
# Se já estiver rodando, a segunda cópia não consegue a porta e encerra sozinha.
if [ -x "$R/usr/sbin/dropbear" ]; then
  chroot "$R" /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/root \
    /usr/sbin/dropbear -R -s -p 127.0.0.1:2222
fi
