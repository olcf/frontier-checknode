#!/usr/bin/env -S python3

# Derived from the ORNL checknode script (bash).  Converted to python,
# modularized, added error checks, signal handling, etc.
# 

# This software is Apache 2.0 licensed 
# Copyright 2024 AMD

# Please see the included LICENSE file for details.

#
# Original developers @ ORNL: Matt Ezell, Nick Hegarty
# Python rewrite @ AMD: Joe Landman, Ken Wright, Vishal Singh
#

import argparse as ap
import os
from pathlib import Path
import re
import signal
import subprocess as sp
import time

t_start = time.time()


SLURM_CONF="/etc/slurm/slurm.conf"
topdir = "/run/checknode"
ALL=False
BOOT=False
CHECKONLY=False
LOCALONLY=False
ERRORCNT=False
ERRORSTR=''
UNDRAIN=False
VERBOSE=False
MANUALNODESCREEN=False
DRYRUN=False
TESTDIR=''



# set up signal handlers so as to do the right thing
# if we catch specific signals
def sig_handler_setup():
   # handle all the signals that will terminate this
   # and send an error to slurm
   signal.signal(signal.SIGQUIT,sigexits)
   signal.signal(signal.SIGINT,sigexits)
   signal.signal(signal.SIGTRAP,sigexits)
   signal.signal(signal.SIGABRT,sigexits)
   signal.signal(signal.SIGALRM,sigexits)
   signal.signal(signal.SIGBUS,sigexits)

   # handle all the signals that will not terminate this
   signal.signal(signal.SIGFPE,sigwarns)
   signal.signal(signal.SIGUSR1,sigwarns)
   signal.signal(signal.SIGUSR2,sigwarns)
   signal.signal(signal.SIGSEGV,sigwarns)
   signal.signal(signal.SIGPIPE,sigwarns)
   signal.signal(signal.SIGCHLD,sigwarns)
   
def sigexits(number,frame):
   print(f"""TERMINAL SIGNAL number {number} caught\n{frame} """)
   # send stuff to slurm

   # remove the lock file
   os.unlink("/run/checknode/lock")
   exit(1)

def sigwarns(number,frame):
   print(f"""NONTERMINAL SIGNAL number {number} caught\n{frame} """)
   # dont send stuff to slurm

#
# Find top level tests directory.  In order, look for
#  1) command line arguments (--testdir=/path/to/testdir
#      --config=/path/to/config --slurm=/path/to/slurm)
#  1) environment variable AMDCHECKNODEDIR
#  2) /etc/amdchecknode.conf
#  3) $HOME/.config/amdchecknode.conf
#  4) current directory amdnodecheck.conf
#
#  In the environment variable case, this will point to a directory with an amdchecknode.conf
#  file.
#  
#  Structure of amdchecknode.conf file are simple key value pairs.
# 
#  Mandatory keys
#
#  key               type           value 
#  TESTDIR           string         path to amdchecknode tests directory
#  SLURM_CONF        string         path to slurm.conf
#
#  Optional keys
#
#  VERBOSE           integer        1 == true, 0 == false


def find_and_read_config(fname=''):
   global TESTDIR, SLURM_CONF, VERBOSE, DRYRUN
   if fname == None:
      fname=''

   # look for AMDCHECKNODEDIR
   if (fname == '') & os.environ.get('AMDCHECKNODEDIR',False):
      fname=os.environ.get('AMDCHECKNODEDIR')
   
   # look for /etc/amdchecknode.conf
   if (fname == '') & exists('/etc/amdchecknode.conf'):
      fname='/etc/amdchecknode.conf'
   
   # look for $HOME/.config/amdchecknode.conf
   if (fname == '') & exists(os.getenv('HOME') + '/.config/amdchecknode.conf'):
      fname=os.getenv('HOME') + '/.config/amdchecknode.conf'
   
   # look for current directory amdchecknode.conf
   if (fname == '') & exists(os.getcwd() + '/amdchecknode.conf'):
      fname=os.getcwd() + '/amdchecknode.conf'

   # if we still don't have a file name (fname) for the config,
   # print an error, and exit with 1
   if fname == '':
      print("Error: unable to find amdchecknode.conf\n")
      exit(1)
   
   with open(fname,"r") as f:
      lines=f.readlines()
   
   # minimal parser, pounds are comments, and only look at material to the 
   # left of them.  Skip blank lines
   for l in lines:
      kvp=l.split("#")[0].rstrip()
      if kvp == '':
         continue # ignore blank lines
      
      kvp_l = kvp.split('=')
      if kvp_l[0] == 'TESTDIR':
         TESTDIR=kvp_l[1]
      
      if kvp_l[0] == 'SLURM_CONF':
         SLURM_CONF=kvp_l[1]
      
      if kvp_l[0] == 'VERBOSE':
         if kvp_l[1] == 0:
            VERBOSE=False
         else:
            VERBOSE=True
         
      if kvp_l[0] == 'DRYRUN':
         if kvp_l[1] == 0:
            DRYRUN=False
         else:
            DRYRUN=True
         

def command_line_options():
   p = ap.ArgumentParser( 
      prog='amdchecknode',
      description='Amdchecknode runs tests to verify node health before a scheduler based job launch'
   )
   #p.add_argument('-a', '--all', action='store_true', help="run all tests")
   p.add_argument('-b', '--boot-mode', action='store_true', help="boot mode")
   #p.add_argument('-c', '--check-node-only', action='store_true', help="check node only")
   #p.add_argument('-l', '--local-checks-only', action='store_true', help="local checks only")
   #p.add_argument('-r', '--node-screen', action='store_true', help="run node screen")
   p.add_argument('-u', '--force-undrain', action='store_true',help="force slurm undrain")
   p.add_argument('-v', '--verbose', action='store_true', help="force verbose")
   p.add_argument('--testdir', help="set test directory")
   p.add_argument('--config', help="set config directory")
   p.add_argument('--slurm', help="set slurm directory")
   #p.add_argument('--parallel', help="run tests in parallel (defaults to serial)")
   #p.add_argument('--timeout', help="timeout in seconds for entire script to complete")
   p.add_argument('--dryrun', action='store_true',help="print test names that would be run without running them")
   args = p.parse_args()
   return args
 
def exists(path):
   p = Path(path)
   return p.exists()

def mkdir(path):
   p = Path(path)
   result = False
   try:
      result = p.mkdir(parents=True,exist_ok=True)
   except:
      pass
   return result

def touch(path):
   p = Path(path)
   result = False
   try:
      result = p.touch(exist_ok=True)
   except:
      pass
   return result

def check_if_running():
   if exists("/run/checknode/lock"):
      if VERBOSE: print("amdchecknode lock in place, amdchecknode is running")
      return True
   return False

def prepare_run_directory():
   return mkdir(topdir)

def set(path,content):
   p = Path(path)
   result = False
   try:
      result = p.open("w").write(content)
   except:
      pass
   return result

def run(cmdstr,timeout=60):
   # run a command, return a return code, stdout, and stderr
   # if thgere is an error running the command, return None, and two blank strings
   try:
      s = sp.run(cmdstr,
                  capture_output=True,
                  shell=True,
                  universal_newlines=True,
                  timeout=timeout
      )
   except:
      return (None,"","")
   
   return (s.returncode, s.stdout, s.stderr)

#
# begin
#



args = command_line_options()
find_and_read_config(fname=args.config)

check_if_running()
if prepare_run_directory() == False:
   if VERBOSE: print(f"Unable to create {topdir}")
   exit(1)

mkdir("/run/checknode/journalcache")
touch("/run/checknode/lock")
if set("/run/checknode/state","running") == False:
   print(f"Unable to create /run/checknode/state ")
   exit(1)

###############################################################################
# Process arguments
###############################################################################

if BOOT:
   touch("/run/checknode/booted")
else:
   # sanity check boot status
   if re.match(r"No jobs running",run('systemctl list-jobs')[1]):
      BOOT=1
      touch("/run/checknode/booted")
   else:
      if VERBOSE: print("Node is still booting\n")
      exit(1)


################################################################################
# tests: return a 0 on success, and non-zero on failure
################################################################################

test_list = os.listdir(TESTDIR)
test_list.sort()
tests = {}

TIMEOUT=10

# run them in serial for now
for test in test_list:
   testname = TESTDIR + '/' + test
   if VERBOSE: print(f"test = {test}, file = {testname}")
   if args.dryrun:
      print(" ... Dry run, not actually running this code\n")
   else:
      if VERBOSE: print(f" Beginning run of {test}")
      t_initial = time.time()
      ret = run(testname,timeout=TIMEOUT)
      t_final = time.time()
      dt = t_final - t_initial
      to = False
      if dt >= TIMEOUT:
         to = True
      tests[test] = {'name': test, 
                     'runtime': t_final-t_initial, 
                     'stderr': ret[2],
                     'stdout': ret[1],
                     'returncode': ret[0],
                     'timed_out': to
                     }
      if VERBOSE: print(f" End of run {test}\n delta t = {t_final-t_initial:.3f}\n return code = {ret[0]}\n stderr = {ret[2]}\n stdout = {ret[1]}\n")

   