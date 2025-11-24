import re
import sys

betweenparenthesis=re.compile("Form [0-9]* \((.*)\),,,,,,,,,")
FormSet=re.compile("FormSet (.*) \(.*\),,,,,,,,,")

unsatisfied={}
cloud={}

# preprocessing
csvarray=[]
for dataline in sys.stdin:
  csvarray.append( dataline.strip() )

N=len(csvarray)

# process a  page. we assume that i points below the Form 1234 (title),,,,,,,,
def process_page(title, starting_line, indent):
  global unsatisfied
  subpages=[ ]
  i=starting_line
  tag="{0:04d}:".format(i)
  sys.stdout.write(tag+"  "*indent+"entering sub page "+ title+'\n')
  while i<N:
    dataline=csvarray[i]
    tag="{0:04d}:".format(i)
#    print(tag)
    i+=1
    if len(dataline)<10:
      sys.stdout.write(tag+"  "*indent+dataline+"\n")
    # clean pre announcement of submenu
    elif dataline[0]==">" and dataline[-9:]==',,,,,,,,,':
      #>PCI Express Root Port 1,,,,,,,,,
      # special case : disregard all ">PCI Express Root Port " except ">PCI Express Root Port 1"
      # if dataline[:23]==">PCI Express Root Port " and dataline!=">PCI Express Root Port 1,,,,,,,,,":
      if ">PCI Express Root Port " in dataline or \
         '>Fia Mux Configuration' in dataline or \
         '>Debug Settings' in dataline or \
         '>Intel Test Menu' in dataline or \
         '>Global Reset Mask configuration' in dataline:
        # forget it
        sys.stdout.write(tag+"  "*indent+"sub page "+ dataline.strip(">, ") + " is ignored\n" )
        pass
      else:  
        title=dataline.strip('\n,> ')
        if title=="Show BIOS Event Log": title="BIOS Event Log Viewer"
        # had it been recorded in cloud previously ?
        if title in cloud.keys():
          p,q=cloud[title]
          i=process_page(title,p,indent+2)
          cloud.pop(title)
        else:
          subpages.append(title)
          unsatisfied[title]=i-1
        # sys.stdout.write(tag+"  "*indent+"sub page "+ title + " was announced\n" )
    # special root menu pre announcement
    elif dataline[:8]=="FormSet " and dataline[-9:]==',,,,,,,,,':
      indent=0
      title=FormSet.match(dataline).group(1)
      subpages.append(title)
      unsatisfied[title]=i-1
      # sys.stdout.write(tag+"  "*indent+"sub page "+ title + " was announced\n" )
    # submenu is starting
    elif dataline[0:5]=="Form " and dataline[-9:]==',,,,,,,,,':
      # some typo replacements
      dataline=dataline.replace("H2OUve Setup", "H2OUve Configuration")
      dataline=dataline.replace("SIO AST2XXX", "SIO AST2600")
      dataline=dataline.replace("NVMe Device Information", "Generic NVME")
      # extract the page name
      title=betweenparenthesis.match(dataline).group(1).strip(' ')
      # special case: nothing had been announced
      if len(subpages)==0:
        # it was time to leave, anyway
        # print( tag+"  "*indent+"empty subtrace {}".format(i-1) )
        return i-1
      elif title in subpages:
        # the title had been properly preannounced as a subpage
        subpages.remove(title)
        unsatisfied.pop(title)
        i=process_page(title, i, indent+2)
      elif title in unsatisfied.keys():
        # the title has not been announced as a subpage of the current page. But it has been previously announced
        return i-1
      else:
        # so, it wasn't predeclared at all, and the list is not empty.
        # read it to a buffer
        if title=="Debug Settings":
          i=process_page("Debug Settings", i, indent+2)
          continue
        else:
          sys.stdout.write(tag+"  "*indent+"Opening "+title+" while unannounced. subpages={}\n".format(subpages))
          j=process_page(title, i, indent+2)
          cloud[title]=(i, j)
          i=j
          continue

    elif dataline[-9:]==',,,,,,,,,':
      title=dataline.strip(', ')
      sys.stdout.write(tag+"  "*indent+'#'*(6+len(title)) +'#'*6+"\n")
      sys.stdout.write(tag+"  "*indent+'#'*5+' '+title+' '+'#'*5+"\n")
      sys.stdout.write(tag+"  "*indent+'#'*(6+len(title)) +'#'*6+"\n")
    else:
      sys.stdout.write(tag+"  "*indent+dataline+"\n")
      pass
  return i

process_page("root", 0, 0)
