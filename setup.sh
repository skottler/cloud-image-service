#/bin/bash/

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root" 1>&2
    exit 1

fi
if [[ `rpm -qa | grep fedmsg-hub -c` -le "0" ]];then
    echo "fedmsg-hub not installed" 1>&2
    exit 1
fi
if [[ `rpm -qa | grep fedmsg-relay -c` -le "0" ]];then
    echo "fedmsg-relay not installed" 1>&2
    exit 1
fi
if [[ `rpm -qa | grep datanommer -c` -le "0" ]];then
    echo "datanommer not installed" 1>&2
    exit 1
fi
if [[ `rpm -qa | grep python-boto -c` -le "0" ]];then
    echo "python-boto not installed" 1>&2
    exit 1
fi

cp fedmsg/fedmsg_check.sh upload/uploader.conf upload/boto.cfg /etc/
#crontab -l > file; echo '* * * * * /etc/fedmsg_check.sh' >> file; crontab file

if [ ! -d "/usr/lib/python2.7/site-packages/uploading_scripts" ]; then
    mkdir /usr/lib/python2.7/site-packages/uploading_scripts
fi
cp upload/fedora_ec2.py upload/uploader.py README.txt  /usr/lib/python2.7/site-packages/uploading_scripts/

#Moves systemd in
cp fedmsgd/* /lib/systemd/system/

#cp fedmsg/base.py fedmsg/ssl.py fedmsg/__init__.py /etc/fedmsg.d/
cp fedmsg/__init__.py /etc/fedmsg.d/
cp fedmsg/__init__.py /usr/lib/python2.7/site-packages/datanommer/consumer/__init__.py

#rm -f file
