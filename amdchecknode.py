#!/usr/bin/env -S python3

import subprocess as sp

#
# Boot-time and run-time diagnostics
# Checks for the presence/health of various components
# Undrain node up if it is healthy
#

usage() {
    echo "Usage: $0 [-a] [-b] [-c] [-h] [-l] [-r] [-u] [-v]"
    echo "  -a all mode - run all tests"
    echo "  -b boot mode - mark the boot sequence as complete"
    echo "  -c check node only - do not change Slurm state"
    echo "  -h print this help message"
    echo "  -l local checks only - avoid network-dependent checks"
    echo "  -r manually run node screen after failure"
    echo "  -u force undrain - clear hand-set drain messages"
    echo "  -v verbose mode"
    echo ""
}


trap "rm -f /run/checknode/lock" EXIT

if [[ -e /run/checknode/lock ]]; then
    echo "Checknode lock already in place"
    logger -t checknode "Checknode lock already in place"
    exit 1
fi

ALL=0
BOOT=0
CHECKONLY=0
LOCALONLY=0
ERRORCNT=0
ERRORSTR=''
UNDRAIN=0
VERBOSE=0
MANUALNODESCREEN=0
export SLURM_CONF=/etc/slurm/slurm.conf.min
mkdir -p /run/checknode
mkdir -p /run/checknode/journalcache
touch /run/checknode/lock
echo "running" > /run/checknode/state
echo -n > /run/checknode/log
[ -L /root/checknode_state ] || ln -sf /run/checknode/state /root/checknode_state
[ -L /root/checknode_log ] || ln -sf /run/checknode/log /root/checknode_log

###############################################################################
# Process arguments
###############################################################################
while getopts "abchlruv" option; do
    case $option in
        a ) ALL=1
            LOCALONLY=0
            ;;
        b ) BOOT=1
            ;;
        c ) CHECKONLY=1
            ;;
        l ) LOCALONLY=1
            SLURM_OK=0
            ;;
        h ) usage
            exit 1
            ;;
        r ) MANUALNODESCREEN=1
            ;;
        u ) UNDRAIN=1
            ;;
        v ) VERBOSE=1
            ;;
        \? ) usage
            exit 1
            ;;
        * ) echo "Option $option not understood"
            usage
            exit 1
            ;;
    esac
done

[ $BOOT -eq 1 ] && touch /run/checknode/booted

if [ $BOOT -eq 0 ]; then
  # sanity check boot status
  if ( systemctl list-jobs | grep -q "No jobs running." ); then
    BOOT=1
    touch /run/checknode/booted
  else
    echo "Node is still booting"
    exit 1
  fi
fi

################################################################################
# checks: return a 0 on success, and 1 on failure
################################################################################

# Check for running jobs
tests/check_for_running_jobs.sh && RUNNINGJOB=1 || RUNNINGJOB=0

HOST=$(hostname)
. includes/functions.sh


###############################################################################
# Check if nodescreen is currently running
###############################################################################
if [[ -e /run/nodescreen/lock ]]; then
    diaginfo "/run/nodescreen/lock in place. Node is currently running nodescreen."
    exit 1
fi


###############################################################################
# Generic checks
###############################################################################
tests/generic_checks


###############################################################################
# Firmware checks
###############################################################################
tests/firmware_checks


###############################################################################
# Process checks
###############################################################################
tests/process_checks


###############################################################################
# Early GPU checks - so the Slurm drain reason becomes this
###############################################################################
### TODO: map for MI300X
tests/early_gpu_checks


###############################################################################
# Stray User Process Check
###############################################################################
tests/stray_user_process_checks


###############################################################################
# Flush caches
###############################################################################
functions/flush_caches


###############################################################################
# CPU Checks
###############################################################################
tests/cpu_checks


###############################################################################
# HSN checks
###############################################################################
tests/hsn_checks


###############################################################################
# GPU checks
###############################################################################
tests/gpu_checks


###############################################################################
# Boot Error Checks
###############################################################################
tests/boot_error_checks

###############################################################################
# NVME Health Checks
###############################################################################
tests/nvme_health_checks

###############################################################################
# File System Checks
###############################################################################
tests/file_system_checks

###############################################################################
# Host Memory Checks
###############################################################################
verbose Checking memory
### TODO: map into MI300X nodes

#compare_ge $(awk '/MemTotal/ {print $2}' /proc/meminfo) 520000000 "Total memory"
#compare_ge $(awk '/MemAvailable/ {print $2}' /proc/meminfo) 460000000 "Available memory"
#compare "$(awk '$2 == "/dev/hugepages" {print $3}' /proc/self/mounts)" "hugetlbfs" "/dev/hugepages is not mounted"
#DMIMEM=$(/usr/sbin/dmidecode --type memory)
#compare $(echo "$DMIMEM" | grep Manufacturer: | sort -u | wc -l) 1 "Number of memory manufacturers"
#compare $(echo "$DMIMEM" | egrep ^[[:space:]]Size: | sort -u | wc -l) 1 "DIMM sizes"
#compare $(echo "$DMIMEM" | egrep ^[[:space:]]Speed: | sort -u | wc -l) 1 "DIMM speeds"
#compare $(echo "$DMIMEM" | awk '/Number Of Devices/ {print $4}') 8 "Count of DIMMs"


###############################################################################
# State Updates
###############################################################################

if [ $ERRORCNT -gt 0 ]; then
  readslurmstate
  echo "fail" > /run/checknode/state
  ERRORSTR2="checknode($ERRORCNT) $(echo "$ERRORSTR"|tr '\n' ';')"
  if [[ $CHECKONLY -eq 1 ]]; then
    logstderr "Node is unhealthy - checkonly mode"
  elif [[ "$CURRENTREASON" == "$ERRORSTR2" ]]; then
    logstderr "Node is unhealthy - reason unchanged"
  elif [[ "$CURRENTREASON" != "checknode"* &&
          "$CURRENTREASON" != "Kill task failed" &&
          "$CURRENTREASON" != "Not responding" &&
          "$CURRENTREASON" != "Prolog error" &&
          "$CURRENTREASON" != "Epilog error" &&
          "$CURRENTREASON" != "SPI job"* &&
          "$CURRENTREASON" != "switch_g_job_postfini failed" &&
          "$CURRENTREASON" != "none" &&
          "$CURRENTREASON" != ""
          ]]; then
    logstderr "Node is unhealthy - not changing existing reason: $CURRENTREASON"
  else
    [ $SLURM_OK -eq 1 ] && logstderr "Node is unhealthy - marking drain"
    [ $SLURM_OK -eq 1 ] && scontrol --local update node=$(hostname) state=drain reason="$ERRORSTR2" > /dev/null
  fi
  if [[ "$ERRORSTR" == *"hsn"* ]] ; then
    logstderr "Stopping slurmd due to hsn errors"
    stopslurmd
  else
    startslurmd
  fi
  exit 1
fi

# If this is initial startup, slurmd might not be running
startslurmd
readslurmstate

# If we made it here, the node is healthy
echo "pass" > /run/checknode/state
# If there's an existing comment in checkonly mode (not rebooting), leave the node down
if [[ $CHECKONLY -eq 1 ||
     "$CURRENTSTATE" == "idle" ||
     "$CURRENTSTATE" == "plnd" ||
     "$CURRENTSTATE" == "maint" ||
     "$CURRENTSTATE" == "resv"
     ]]; then
  logstdout "Node is healthy - not changing state from $CURRENTSTATE"
elif [[ "$CURRENTREASON" == "Node unexpectedly rebooted" && $UNDRAIN -eq 0 ]]; then
  logstdout "Node is healthy - NOT clearing unexpected reboot - use 'checknode -u' to clear IF you understand the reboot reason"
elif [[ "$CURRENTREASON" != "checknode"* &&
        "$CURRENTREASON" != "Kill task failed" &&
        "$CURRENTREASON" != "Not responding" &&
        "$CURRENTREASON" != "SPI job"* &&
        "$CURRENTREASON" != "switch_g_job_postfini failed" &&
        "$CURRENTREASON" != "none" &&
        $UNDRAIN -eq 0
        ]]; then
  logstderr "Node is healthy - not changing existing reason: '$CURRENTREASON' - use 'checknode -u' to clear IF you know it is safe to clear"
else
  [ $SLURM_OK -eq 1 ] && logstdout "Node is healthy - marking online" || echo "Node is healthy - not contacting slurm"
  [ $SLURM_OK -eq 1 ] && scontrol --local update node=$(hostname) state=idle > /dev/null
fi

exit 0
# vim: ai:ts=2:sw=2:syn=sh
