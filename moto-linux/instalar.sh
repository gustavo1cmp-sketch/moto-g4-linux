#!/system/bin/sh
# Roda uma vez no celular, como root: instala o Alpine a partir dos arquivos em /data/local/tmp.
set -e
R=/data/linux/alpine
T=/data/local/tmp
[ -e "$R" ] && { echo "$R ja existe; nada foi alterado"; exit 1; }

mkdir -p "$R"
chmod 700 /data/linux
/data/adb/magisk/busybox tar -xzf "$T/alpine.tar.gz" -C "$R"
printf 'nameserver 1.1.1.1\nnameserver 8.8.8.8\n' > "$R/etc/resolv.conf"

mkdir -p "$R/root/.ssh"
cp "$T/chave.pub" "$R/root/.ssh/authorized_keys"
chmod 700 "$R/root/.ssh"
chmod 600 "$R/root/.ssh/authorized_keys"

cp "$T/linux.sh" /data/adb/service.d/linux.sh
chmod 755 /data/adb/service.d/linux.sh
sh /data/adb/service.d/linux.sh # monta; o SSH ainda não está instalado

chroot "$R" /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/root \
  /sbin/apk add --no-progress dropbear openssh-sftp-server
sh /data/adb/service.d/linux.sh # agora sobe o SSH
echo INSTALADO
