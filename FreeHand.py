#!/usr/bin/python3

import os
import re          # regex
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
reboot_timeout = 20*6             # how long does it take to reboot, in 10s unit
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


def planB(target_bmc, bmcuser, bmcpass):
  # could have switched off by itself
  # could be doing fsck 
  # could have rebooted on a different OS (grub entry)
  sys.stdout.write("\nplan B was invoked\n")
  requests.post(
      "https://"+target_bmc+"/redfish/v1/Systems/system/Actions/ComputerSystem.Reset",
      json={"ResetType": "On"},
      headers={"Content-Type": "application/json",
               "Accept"      : "application/json"},
      verify=False,
      auth=(bmcuser, bmcpass)
      ) 
  # if stuck in bios init, then factory reset (will turn off),
  # then power on, then position settings again


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
  parser.add_argument("--bios-param", "-b", metavar="<name=value>", action="store",
           required=True,
           help="bios parameter to commute. Exact case sensitive names and exact values "
           "must be offered. If the parameter already has that value, no test will be "
           "performed. "
           "Example : --bios-param \"Disable ACP=Yes\"")
 
  parser.add_argument("--verbose",  "-v", action="store_true", default=False)
  parser.add_argument("--skip-bench",     action="store_true", default=False)
  parser.add_argument("--revert",   "-r", action="store_true", default=False,
           help="whatever was changed, needs to be reverted - currently not implemented" )
  parser.add_argument("--no-reboot",  "-n", action="store_true", default=False,
           help="skip the reboot phase. Will also not verify the value of the parameter "
                "after reboot, and will skip the preconfiguration phase. (Together with "
                "--skip-bench, the tool essentially becomes a mean to set a bios settings "
                "remotely).")


  return parser.parse_args()
    

if __name__ == "__main__":
  args=init()
  verbose     = args.verbose
  skip_bench  = args.skip_bench
  left,right  = args.bios_param.split("=",1)
  param_name  =  left.strip(" ")
  param_value = right.strip(" ")
  if target_bmc is None:
    target_bmc= getBMC(target_ip)

  sys.stdout.write("Setting BIOS parameter : \"{}\"\t= \"{}\"\n".format(param_name, param_value))  
  commande=[ "ssh", "root@"+target_ip, 
             "h2ouve-lx64", "-ms", "-fi", '"'+param_name+'"', "-op", '"'+param_value+'"']
  p=subprocess.Popen( commande, stderr=subprocess.STDOUT, stdout=subprocess.PIPE, universal_newlines=True )
  s=False
  for dataline in p.stdout:
    if "Insyde" in dataline: continue
    if "Please note" in dataline: continue
    if dataline.strip("\n ") == "": continue
    if verbose: sys.stdout.write(dataline)
    s=s or "Modify SCU settings successfully" in dataline
  
  if not s:
    sys.stdout.write("h2ouve was unsuccessful. Maybe the value was already set ?\n") 
    sys.exit(1)
  
  if not args.no_reboot:  
    sys.stdout.write("Rebooting via the bmc at "+target_bmc+" ") ; sys.stdout.flush()
    # Pre halt step, i need to umount /hana/log by hand on this one specific install
    p=subprocess.Popen( [ "ssh", "root@"+target_ip, "umount /hana/log" ],
             stderr=subprocess.STDOUT, stdout=subprocess.PIPE, universal_newlines=True )
    #ready to reboot
    requests.post(
        "https://"+target_bmc+"/redfish/v1/Systems/system/Actions/ComputerSystem.Reset",
        json={"ResetType": "GracefulRestart"},
        headers={"Content-Type": "application/json",
                 "Accept"      : "application/json"},
        verify=False,
        auth=(bmcuser, bmcpass)
      )
    #waiting
    T=2
    sys.stdout.write("-") ; sys.stdout.flush()
    time.sleep(20)
  
    # doubling with Power cycle
    # ResetType in ["On", "ForceOff", "ForceOn", "ForceRestart", "GracefulRestart",
    # "GracefulShutdown", "PowerCycle","Nmi" ]
    #T+=1
    #sys.stdout.write("+") ; sys.stdout.flush()
    #requests.post(
    #    "https://"+target_bmc+"/redfish/v1/Systems/system/Actions/ComputerSystem.Reset",
    #    json={"ResetType": "PowerCycle"},
    #    headers={"Content-Type": "application/json",
    #             "Accept"      : "application/json"},
    #    verify=False,
    #    auth=(bmcuser, bmcpass)
    #  )
    #time.sleep(10)
  
    #waiting
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
      planB(target_bmc, bmcuser, bmcpass)
     
    # here, the mesca5 has rebooted
    sys.stdout.write("\n")
    
    # let's process the output of our command
    for dataline in p.stdout:
      if "Insyde" in dataline: continue
      if "Please note" in dataline: continue
      if dataline.strip("\n ") == "": continue
      if verbose: sys.stdout.write(dataline)
    
    fields=dataline.strip().split('\"')
    sys.stdout.write("Reading BIOS parameter : {} = {}\n".format(fields[1], fields[3]))
    
    # preconfig
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
  
  # run bench
  if not skip_bench:
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
        if not verbose: break
    p.wait()
    if not verbose:
      sys.stdout.write("\n")
    
    
    # recover the score
    sys.stdout.write("reading results in : " + outputfile+"\n")
    commande=["ssh", "root@"+target_ip, "cat", outputfile ]
    p=subprocess.Popen( commande, stderr=subprocess.STDOUT, stdout=subprocess.PIPE, universal_newlines=True )
    base=""
    peak=""
    for dataline in p.stdout:
      if dataline[0]=="#": continue
      # 525.x264_r          240        278       1510  *     240        262       1600  *
      # Est. SPECrate(R)2017_int_base           1440
      # Est. SPECrate(R)2017_int_peak
      if "SPECrate(R)2017_int_base" in dataline:
        fields=dataline.strip().split()
        base=fields[-1]
        continue

      if "SPECrate(R)2017_int_peak" in dataline:
        fields=dataline.strip().split()
        peak=fields[-1]
        break
    print("base="+base+"\tpeak="+peak)  
