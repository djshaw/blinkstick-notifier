# Multipass

`blinkstick-notifier` has been developed to run in multipass.  Running `blinkstick-notifier` on a
virtual machine keeps the hosts container environment clean, and contains any negative affects.

## Setting up a Multipass VM

Start a new Multipass vm with:

```Shell
multipass launch 23.04 --name blinkstick \
                       --disk 25G \
                       --cpus 2 \
                       --memory 2GB
```

### Attaching the Blinkstick USB Device

Attach the blinkstick to the VM with:

```Shell
virsh attach-device blinkstick --file devices.xml --persistent
```

Verify that the device is attached to the VM with:

```Shell
$ virsh dumpxml blinkstick | xq -x //domain/devices/hostdev/source/vendor/@id
0x20a0
```

If the device has been attached successfully, the device id will be printed.  The device id is
always `0x20a0`.  If the device is not attached to the vm, there is no output.

From within the vm, we can verify that the device is attached with:

```Shell
$ lsusb
Bus 001 Device 002: ID 20a0:41e5 Clay Logic BlinkStick
Bus 001 Device 001: ID 1d6b:0001 Linux Foundation 1.1 root hub
```

Revert the attachment with:

```Shell
virsh detach-device blinkstick devices.xml
```

## The client is not authenticated with the Multipass service

`multipass` commands will occasionally start to fail with the message:

```Shell
$ multipass shell blinkstick
shell failed: The client is not authenticated with the Multipass service.
Please use 'multipass authenticate' before proceeding.
```

This is a [known issue](https://multipass.run/docs/authenticating-clients#heading--in-case-client-cannot-authorize-and-the-passphrase-cannot-be-set)
and can be resolved with:

```Shell
cat ~/snap/multipass/current/data/multipass-client-certificate/multipass_cert.pem | sudo tee -a /var/snap/multipass/common/data/multipassd/authenticated-certs/multipass_client_certs.pem > /dev/null
snap restart multipass
```
