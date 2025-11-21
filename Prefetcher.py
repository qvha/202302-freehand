#!/usr/bin/python3

import os
import re          # regex
import csv         # to read the csv output of h2ouve
import sys
import time        # for time.sleep, required to restart wait for reboot
import shutil      # for chown and copyfile. Requires python >= 3.3
import socket      # for tcping
import requests
import argparse
import subprocess


######################## Internal settings #####################################
target_bmc     = None             # if None, then will be automatically detected
target_ip      = "10.197.176.122"
bmcuser        = "admin"
bmcpass        = "0penBmc*"
verbose        = False 
revert         = False
reboot_timeout = 10*6             # how long does it take to reboot, in 10s unit
specint        = "/hana/log/specCPU2017"
################################################################################


# this, to disable the InsecureRequestWarning from requests.post()
import urllib3
urllib3.disable_warnings()


def ping_server(server: str, port: int, timeout=.001):
    """ping server
       timeout : timeout in second (float)
    """
    try:
        socket.setdefaulttimeout(timeout)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((server, port))
    except OSError as error:
        return False
    s.close()
    return True


def redfish_reset(reset_type, target_bmc, bmcuser, bmcpass):
  # reset_type in ["On", "ForceOff", "ForceOn", "ForceRestart", "GracefulRestart",
  # "GracefulShutdown", "PowerCycle","Nmi" ]
  requests.post(
      "https://"+target_bmc+"/redfish/v1/Systems/system/Actions/ComputerSystem.Reset",
      json={"ResetType": reset_type},
      headers={"Content-Type": "application/json",
               "Accept"      : "application/json"},
      verify=False,
      auth=(bmcuser, bmcpass)
      )


def planB(target_bmc, bmcuser, bmcpass):
  # could have switched off by itself
  # could be doing fsck 
  # could have rebooted on a different OS (grub entry)
  redfish_reset("ForceOff",target_bmc, bmcuser, bmcpass)
  time.sleep(20)
  redfish_reset("ForceOn", target_bmc, bmcuser, bmcpass)  # ForceOn has been tried, not working (after 10s)


def planC(target_bmc, bmcuser, bmcpass):
  # planB has failed. Most likely off, and not turning on
  time.sleep(40)
  redfish_reset("On", target_bmc, bmcuser, bmcpass)


def getBMC(target_ip):
  commande=[ "ssh", "root@"+target_ip, "ipmitool", "lan", "print", "1"]
  p=subprocess.Popen( commande, stderr=subprocess.STDOUT, stdout=subprocess.PIPE, universal_newlines=True )
  # IP Address              : 10.197.176.121
  for dataline in p.stdout:
    if "IP Address    " in dataline:
       fields=dataline.split(":")
       return fields[1].strip()
  sys.stdout.write("Failed to find the BMC of "+target_ip +"\n")
  sys.exit(1)

    
def init():
  parser = argparse.ArgumentParser(description="positions, reboots, check positions, "
           "preconfigures, benches, reports.",
           epilog="(c) 2023 HA Quoc Viet" )
 
  parser.add_argument("--switch", "-s", metavar="<bios knob>", action="append",
           help="bios parameter to switch. Exact case sensitive names "
           "must be offered. Can be specified many times. Requires a h2ouve csv "
           "output of the current bios settings in the same folder. "
           "Example : -s \"Disable ACP\" -s \"KTI prefetch\"")
 
  parser.add_argument("--verbose",  "-v",   action="store_true", default=False)
  parser.add_argument("--dry-run",          action="store_true", default=False)
  parser.add_argument("--skip-bench",       action="store_true", default=False)
  parser.add_argument("--prefetchers","-p", action="store_true", default=False,
           help="Adds a list of predefined bios knobs, known as the prefetchers")
  parser.add_argument("--no-reboot",  "-n", action="store_true", default=False,
           help="skip the reboot phase. Will also skip the preconfiguration phase "
                "which occurs after reboot. (Together with "
                "--skip-bench, the tool essentially becomes a mean to set a bios settings "
                "remotely).")
  parser.add_argument("--switch-value")    # hidden "argument", just for the internal logic 
  parser.add_argument("--switch-options")  # hidden "argument", just for the internal logic 

  parser_results=parser.parse_args()

  # initialize internal code variables
  global target_bmc
  global target_ip
  if target_bmc is None:
    target_bmc= getBMC(target_ip)

  # now, check the input against the bios settings in the h2ouve file, drop the unknown ones,
  # build the final list of bios_knobs to tinker with, store their current positions
  if parser_results.switch is None:
    parser_results.switch=list()

  if parser_results.prefetchers==True:
    parser_results.switch += [ 
      "KTI Prefetch",
      "Hardware Prefetcher",
      "L2 RFO Prefetch Disable",
      "Adjacent Cache Prefetch",
      "DCU Streamer Prefetcher",
      "DCU IP Prefetcher",
      "LLC Prefetch",
      "Homeless Prefetch",
      "AMP Prefetch",
      "XPT Prefetch" ]
  
  # remove duplicates
  parser_results.switch = list( set( parser_results.switch ) )

  # rule out the special case where no argument has been passed at all
  if len(parser_results.switch)==0:
    parser.print_help()
    sys.exit(0)
      
  # let's find out the current bios settings, from the latest csv file in the folder, assuming it's
  # a valid h2ouve output
  mostrecent_file=""

  with os.scandir(".") as it:
    mostrecent_ctime=0   # ctime creation date in second
    for entry in it:
        if not entry.name.startswith('.') and entry.is_file():
            # only ".csv" files
            if ".csv" not in entry.name[-4:]:
              # skip this entry, move to the next directory entry object 
              continue
            systat=entry.stat()
            if systat.st_ctime>mostrecent_ctime:
                mostrecent_ctime=systat.st_ctime
                mostrecent_file=entry.name
  
  if len(mostrecent_file)==0:
    sys.stdout.write("Fatal error : could not find the latest csv file the current folder, exiting.\n")
    sys.exit(1)

  # let's find out the position of each knobs in that file
  # initialize the result
  bios_knob_settings=[ None for knob in parser_results.switch ]
  bios_knob_options =[ None for knob in parser_results.switch ]

  with open(mostrecent_file) as csvfile:
    datalines = csv.reader(csvfile, dialect='excel')
    for dataline in datalines:
      for i,knob in enumerate(parser_results.switch):
        if len(dataline)>7  and knob == dataline[5]:
           bios_knob_settings[i]=dataline[6] 
           bios_knob_options [i]=dataline[7].split(",") 

  # pruning out unfound settings
  for i in range( bios_knob_settings.count(None) ):
      u=bios_knob_settings.index(None)
      bios_knob_settings.pop(u)
      bios_knob_options.pop(u)
      key=parser_results.switch.pop(u)
      sys.stdout.write("Warning : skipping BIOS option \""+key+"\" which could not be found in "+mostrecent_file +"\n")

  parser_results.switch_value=bios_knob_settings
  parser_results.switch_options=bios_knob_options

  return parser_results
    

def switch_the_switches(args):    
  knobs       = args.switch
  knob_values = args.switch_value
  knob_options= args.switch_options

  for i,knob in enumerate(knobs):
    current_value=args.switch_value[i]  
    options=list( knob_options[i] )
    options.remove(current_value)
    # axiome du choix  
    next_value=options[0]
      
    sys.stdout.write("Setting BIOS parameter : {0:25s} = \"{1}\"\n".format("\""+knob+"\"", next_value))  
    if args.dry_run: continue

    commande=[ "ssh", "root@"+target_ip, 
               "h2ouve-lx64", "-ms", "-fi", '"'+knob+'"', "-op", '"'+next_value+'"']
    p=subprocess.Popen( commande, stderr=subprocess.STDOUT, stdout=subprocess.PIPE, universal_newlines=True )
    s=False
    for dataline in p.stdout:
      if "Insyde" in dataline: continue
      if "Please note" in dataline: continue
      if dataline.strip("\n ") == "": continue
      if verbose: sys.stdout.write(dataline)
      s=s or "Modify SCU settings successfully" in dataline
  
    if not s:
      sys.stdout.write("h2ouve was unsuccessful. Maybe the latest bios output is not fresh ?\n") 
      sys.exit(1)
  

def reboot(args):  
  global target_bmc
  global target_ip
  global bmcuser
  global bmcpass

  has_rebooted = args.no_reboot  
  gravity=0
  reset_mode=[ "GracefulRestart", "ForceRestart", "PowerCycle", "On", "ForceOn" ]
      # reset_mode is one of ["On", "ForceOff", "ForceOn", "ForceRestart", "GracefulRestart",
      # "GracefulShutdown", "PowerCycle","Nmi" ]

  while not has_rebooted and gravity<len(reset_mode):
    sys.stdout.write("Rebooting via the bmc at "+target_bmc+" through "+reset_mode[gravity]+" ") ; sys.stdout.flush()

    # pre shutdown 
    if gravity==0:  
      # Pre halt step, i need to umount /hana/log by hand on this one specific install
      p=subprocess.Popen( [ "ssh", "root@"+target_ip, "umount /hana/log" ],
                         stderr=subprocess.STDOUT, stdout=subprocess.PIPE, universal_newlines=True )
      p=subprocess.Popen( [ "ssh", "root@"+target_ip, "sync", ";", "sleep", "6" ],
                         stderr=subprocess.STDOUT, stdout=subprocess.PIPE, universal_newlines=True )
    elif gravity==4:
      sleep(60)
      
    #ready to reboot
    redfish_reset(reset_mode[gravity], target_bmc, bmcuser, bmcpass)

    #waiting
    T=2
    sys.stdout.write(".") ; sys.stdout.flush()
    while T<=reboot_timeout:
      # attempt to check the bios value upon reboot, with an ssh timeout of 10s
      p=subprocess.Popen( [ "ssh", "-o", "ConnectTimeout=10", "root@"+target_ip, "h2ouve-lx64",
        "-ms", "-fi", '"'+param_name+'"' ],
             stderr=subprocess.STDOUT, stdout=subprocess.PIPE, universal_newlines=True )
      p.wait()
      if p.returncode==0: # success
        break
      # ssh failed, it is still rebooting
      sys.stdout.write(".") ; sys.stdout.flush()
      T+=1
      time.sleep(10)
    
    if T>reboot_timeout:
      # then loop back, try harder   
      gravity+=1  
      continue

    # here, we think that ,the mesca5 has rebooted
    sys.stdout.write("\n")
    
    # let's process the output of our command
    for dataline in p.stdout:
      if "Insyde" in dataline: continue
      if "Please note" in dataline: continue
      if dataline.strip("\n ") == "": continue
      if verbose: sys.stdout.write(dataline)
    
    fields=dataline.strip().split('\"')
    try: 
      sys.stdout.write("Reading BIOS parameter : {} = {}\n".format(fields[1], fields[3]))
    except:
      # the system needs to be rebooted, last chance
      gravity+=1
      continue

    has_rebooted=True
  
  # end of while

  if has_rebooted==False or gravity>=len(reset_mode):
    sys.stdout.write("really cannot reboot this system, leaving.\n")
    sys.exit(1)

  # preconfig
  if not args.no_reboot:
    sys.stdout.write("preconfig : \n")
    commande=["ssh", "root@"+target_ip, "/root/InitSteps.sh"]
    # currently holds :
    # allow all visible C-states
    # echo " - allowing all C-states"
    # cpupower idle-set -E
    # mount the problematic filesystem
    # echo " - mounting /hana/log"
    # mount -t xfs -o rw,noatime,inode64,logbufs=8,logbsize=32k,sunit=256,swidth=512,noquota  UUID=fbfa0f7f-9221-49e3-86d7-bc6298485f48 /hana/log
    # don't obey frequency limitations from the BIOS
    # echo " - Ignore frequency limits from the BIOS"
    # echo 1 > /sys/module/processor/parameters/ignore_ppc
    p=subprocess.Popen( commande, stderr=subprocess.STDOUT, stdout=subprocess.PIPE, universal_newlines=True )
    for dataline in p.stdout:
      sys.stdout.write(dataline)
    p.wait()
  # end of if args.no_reboot
  

def run_bench(args):
    global target_ip
    global specint

    sys.stdout.write("running bench : ")
    outputfile=""
    commande=["ssh", "root@"+target_ip, '( cd '+specint+' ; . shrc ; . runme.sh )']
    p=subprocess.Popen( commande, stderr=subprocess.STDOUT, stdout=subprocess.PIPE, universal_newlines=True )
    for dataline in p.stdout:
      if verbose: sys.stdout.write(dataline)
      else:       sys.stdout.write(".") ; sys.stdout.flush()
      #     format: Text -> /home/qvha/specCPU2017/result/CPU2017.107.intrate.refrate.txt
      if "format: Text" in dataline:
        outputfile=dataline.strip().split(" -> ")[1] 
        if not args.verbose: break
    p.wait()
    if not args.verbose:
      sys.stdout.write("\n")
    
    # recover the score
    sys.stdout.write("reading results in : " + outputfile+"\n")
    commande=["ssh", "root@"+target_ip, "cat", outputfile ]
    p=subprocess.Popen( commande, stderr=subprocess.STDOUT, stdout=subprocess.PIPE, universal_newlines=True )
    base=None
    peak=None
    for dataline in p.stdout:
      if dataline[0]=="#": continue
      # 525.x264_r          240        278       1510  *     240        262       1600  *
      # Est. SPECrate(R)2017_int_base           1440
      # Est. SPECrate(R)2017_int_peak
      if "SPECrate(R)2017_int_base" in dataline:
        fields=dataline.strip().split()
        base=fields[-1]
        try:
          base=int(base)
        except:
          base=None
        continue

      if "SPECrate(R)2017_int_peak" in dataline:
        fields=dataline.strip().split()
        peak=fields[-1]
        try:
          peak=int(peak)
        except:
          peak=None  
        break
    
    return ( base, peak )


if __name__ == "__main__":
  args=init()

  switch_the_switches(args)

  if not args.no_reboot and not args.dry_run:
    reboot(args)  

  if not args.skip_bench and not args.dry_run:
    score=run_bench(args)
    print("base={0}\tpeak={1}", score[0], score[1])  
