#!/bin/sh
set -eu
# Only these two new files were installed. The original firmware was not replaced.
# Disabling the gate restores the previous boot path; keep its files for review.
if [ -L /etc/rc.d/S09mu300-charge-mode ]; then
    [ "$(readlink /etc/rc.d/S09mu300-charge-mode)" = ../init.d/mu300-charge-mode ] || {
        echo 'Unexpected startup link; inspect it before rollback.' >&2; exit 1;
    }
    rm /etc/rc.d/S09mu300-charge-mode
fi
sync
echo 'Charging gate disabled. The previous boot behavior applies on the next boot.'
