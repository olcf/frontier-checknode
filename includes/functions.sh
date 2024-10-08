
###############################################################################
# Functions
###############################################################################
logstdout()    { echo "DIAG: $1" | tee -a /run/checknode/log; logger -- checknode: DIAG: $1; }
logstderr()    { echo "DIAG_ERROR: $@" | tee -a /run/checknode/log 1>&2; logger -- checknode: DIAG_ERROR: $1; }
diagerror()    { ((ERRORCNT++));logstderr "$@"; [ -z "$ERRORSTR" ] && ERRORSTR="$@"; return 1; }
diaginfo()     { logstdout "$1"; return 1; }
compare()      { [[ "$1" ==  "$2" ]] || diagerror "$3 - Got '$1' but expected '$2'"; }
compare_info() { [[ "$1" ==  "$2" ]] || diaginfo "$3 - Got '$1' but expected '$2'"; }
compare2()     { [[ "$1" ==  "$2" || "$1" == "$3" ]] || diagerror "$4 - Got '$1' but expected '$2' or '$3'"; }
compare3()     { [[ "$1" ==  "$2" || "$1" == "$3" || "$1" == "$4" ]] || diagerror "$5 - Got '$1' but expected '$2', '$3', or '$4'"; }
compare4()     { [[ "$1" ==  "$2" || "$1" == "$3" || "$1" == "$4" || "$1" == "$5" ]] || diagerror "$6 - Got '$1' but expected '$2', '$3', $4, or '$5'"; }
compare_ne()   { [[ "$1" !=  "$2" ]] || diagerror "$3 - Should not get value '$2'"; }
compare_ge()   { [[ "$1" -ge "$2" ]] || diagerror "$3 - Got '$1' but expected >= '$2'"; }
compare_le()   { [[ "$1" -le "$2" ]] || diagerror "$3 - Got '$1' but expected <= '$2'"; }
compare_re()   { [[ "$1" =~ $2 ]] || diagerror "$3 - Expected '$1' to match regex '$2'"; }
compare_nre()  { [[ "$1" =~ $2 ]] && diagerror "$3 - Matched '$1' with regex '$2'"; }
checkproc()    { pgrep -f $1 >/dev/null || diagerror "$1 is not running"; }
checkkmod()    { lsmod|egrep -q "^$1" || diagerror "Kernel module $1 is not loaded"; }
run()          { OUT="$($@)"; [ $? -ne 0 ] && diagerror $OUT ; }
verbose()      { [ $VERBOSE -eq 1 ] && echo checknode: $(date -Iseconds) - $@; }
startslurmd()  { pgrep slurmd >/dev/null 2>&1 || ([ $SLURM_OK -eq 1 ] && systemctl start slurmd && sleep 35) }
stopslurmd()   { pgrep slurmd >/dev/null 2>&1 && systemctl stop slurmd; }
readslurmstate() { [ $SLURM_OK -eq 1 ] && read -t 5 CURRENTSTATE FULLSTATE REASONUSER CURRENTREASON < <(sinfo -n $(hostname -s) -N --local -O statecompact:20,statecomplete:50,user,reason:150 --noheader |head -1) || CURRENTSTATE="unknown"; }
# journalgrep looks for lines in the journal, caching results
# Expects arguments:
#   $1 a name to store the cache as
#   $2 a 'grep' of what to look for (-g argument to journalctl)
#   $3 error to report back to checknode
journalgrep()  { CFILE=/run/checknode/journalcache/$1
                 [ -e $CFILE ] && SINCE="$(stat -c %y $CFILE| sed 's/\..*//')" || SINCE="-1y"
                 touch $CFILE
                 journalctl -q -g "$2" --since "$SINCE" >> $CFILE
                 [ $(cat $CFILE | wc -l) -gt 0 ] && diagerror "$3"
               }
