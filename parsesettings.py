#!/usr/bin/python3
# usage : parsesettings.py bios-2024121212.txt
# returns : a list of settings, that can be copied and pasted into excel

import sys

debug=False

keys=[ 
     "Averaging Time Window",
#     "Disable ACP",
#     "Energy Efficient Turbo",
#     "Stale AtoS",
#     "Hardware P-States",
#     "ADDDC Sparing",
#     "Enable Monitor MWAIT",
#     "Power Performance Tuning",
#     "Enhanced Halt State (C1E)",
#     "ENERGY_PERF_BIAS_CFG mode",
#     "PL2 Time Window",
#     "EPP Enable",
#     "Package C State",
#     "LLC Prefetch",
#     "Platform RAPL Limit&Info",
#     "PL1 Time Window",
#     "Current Limit Override",
#     "IE Agent",
#     "Legacy Agent",
#     "SMBus Agent",
#     "Generic Agent",
#     "eSPI Agent",
#     "DfxRedManu Agent",
#     "DfxOrange Agent",
#     "DCU Streamer Prefetcher",
#     "SNC",
#     "Reserved PM Parameter",
#     "CPU Flex Ratio Override",
#     "SpeedStep (Pstates)",
#     "OSB Enabled",
#     "Application Profile Configuration",
#     "DBP-F",
#     "HD Audio",
#     "Optimized Power Mode"
     ]
# 0: not in a section ; 1: in standard section with a * ; 2: in Setting: [0]
selector=0
result={}
key=None

for dataline in open(sys.argv[1], "r"):
      if dataline[0]=="#": continue
      if dataline[0]==">": continue
      if "***" in dataline: continue

      if selector==1 and "*" in dataline:
          fields=dataline.split("*")
          if debug: print("{0}\t{1}".format(key, fields))
          result[key]=fields[1].strip("] \n")
          selector=0
      elif selector==2 and "Setting:" in dataline:
          fields=dataline.split(":")
          if debug: print(fields)
          #  Setting: [0]
          result[key]=fields[1].strip(" []\n")
          selector=0

      else:
          for k in keys:
              if k in dataline[-len(k)-1:-1]:
                 key=k 
                 if "Reserved PM Parameter" in k:
                   selector=2
                 elif "Averaging Time Window" in k:
                   selector=2
                 else:  
                   selector=1
                 break

#find missing keys, and add fillers
A=set(keys)
B=set(result.keys())
for key in A-B:
    result[key]=""

# output to stdout
print( ";".join(keys))    
print(";".join([ result[key] for key in keys ]))
