#
# Copyright (c) 2017 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import os

from sysinv.common import constants
from sysinv.common import exception
from sysinv.openstack.common import log as logging

from tsconfig import tsconfig

from . import base

LOG = logging.getLogger(__name__)

HOSTNAME_INFRA_SUFFIX = '-infra'

NOVA_UPGRADE_LEVEL_NEWTON = 'newton'
NOVA_UPGRADE_LEVELS = {'17.06': NOVA_UPGRADE_LEVEL_NEWTON}


class PlatformPuppet(base.BasePuppet):
    """Class to encapsulate puppet operations for platform configuration"""

    def get_static_config(self):
        config = {}
        config.update(self._get_static_software_config())
        return config

    def get_secure_static_config(self):
        config = {}
        config.update(self._get_secure_amqp_config())
        return config

    def get_system_config(self):
        config = {}
        config.update(self._get_system_config())
        config.update(self._get_hosts_config())
        config.update(self._get_amqp_config())
        config.update(self._get_resolv_config())
        config.update(self._get_haproxy_config())
        config.update(self._get_sdn_config())
        config.update(self._get_region_config())
        config.update(self._get_distributed_cloud_role())
        config.update(self._get_sm_config())
        config.update(self._get_firewall_config())
        config.update(self._get_drbd_sync_config())
        config.update(self._get_nfs_config())
        config.update(self._get_remotelogging_config())
        config.update(self._get_snmp_config())
        return config

    def get_secure_system_config(self):
        config = {}
        config.update(self._get_user_config())
        return config

    def get_host_config(self, host, config_uuid):
        config = {}
        config.update(self._get_host_platform_config(host, config_uuid))
        config.update(self._get_host_ntp_config(host))
        config.update(self._get_host_sysctl_config(host))
        config.update(self._get_host_drbd_config(host))
        config.update(self._get_host_upgrade_config(host))
        return config

    def _get_static_software_config(self):
        return {
            'platform::params::software_version': tsconfig.SW_VERSION,
        }

    def _get_secure_amqp_config(self):
        return {
            'platform::amqp::params::auth_password':
                self._generate_random_password(),
        }

    def _get_system_config(self):
        system = self._get_system()

        return {
            'platform::params::controller_upgrade': False,
            'platform::params::config_path': tsconfig.CONFIG_PATH,
            'platform::params::security_profile': system.security_profile,

            'platform::config::params::timezone': system.timezone,
        }

    def _get_hosts_config(self):
        # list of host tuples (host name, address name, newtork type) that need
        # to be populated in the /etc/hosts file
        hostnames = [
            # management network hosts
            (constants.CONTROLLER_HOSTNAME,
             constants.CONTROLLER_HOSTNAME,
             constants.NETWORK_TYPE_MGMT),

            (constants.CONTROLLER_0_HOSTNAME,
             constants.CONTROLLER_0_HOSTNAME,
             constants.NETWORK_TYPE_MGMT),

            (constants.CONTROLLER_1_HOSTNAME,
             constants.CONTROLLER_1_HOSTNAME,
             constants.NETWORK_TYPE_MGMT),

            (constants.CONTROLLER_PLATFORM_NFS,
             constants.CONTROLLER_PLATFORM_NFS,
             constants.NETWORK_TYPE_MGMT),

            (constants.CONTROLLER_CGCS_NFS,
             constants.CONTROLLER_CGCS_NFS,
             constants.NETWORK_TYPE_MGMT),

            # pxeboot network hosts
            (constants.PXECONTROLLER_HOSTNAME,
             constants.CONTROLLER_HOSTNAME,
             constants.NETWORK_TYPE_PXEBOOT),

            # oam network hosts
            (constants.OAMCONTROLLER_HOSTNAME,
             constants.CONTROLLER_HOSTNAME,
             constants.NETWORK_TYPE_OAM),

            # cinder storage hosts
            (constants.CONTROLLER_CINDER,
             constants.CONTROLLER_CINDER,
             constants.NETWORK_TYPE_MGMT),

            (constants.CONTROLLER_CINDER,
             constants.CONTROLLER_CINDER,
             constants.NETWORK_TYPE_INFRA),

            # ceph storage hosts
            (constants.STORAGE_0_HOSTNAME,
             constants.STORAGE_0_HOSTNAME,
             constants.NETWORK_TYPE_MGMT),

            (constants.STORAGE_1_HOSTNAME,
             constants.STORAGE_1_HOSTNAME,
             constants.NETWORK_TYPE_MGMT),

            # infrastructure network hosts
            (constants.CONTROLLER_0_HOSTNAME + HOSTNAME_INFRA_SUFFIX,
             constants.CONTROLLER_0_HOSTNAME,
             constants.NETWORK_TYPE_INFRA),

            (constants.CONTROLLER_1_HOSTNAME + HOSTNAME_INFRA_SUFFIX,
             constants.CONTROLLER_1_HOSTNAME,
             constants.NETWORK_TYPE_INFRA),

            (constants.STORAGE_0_HOSTNAME + HOSTNAME_INFRA_SUFFIX,
             constants.STORAGE_0_HOSTNAME,
             constants.NETWORK_TYPE_INFRA),

            (constants.STORAGE_1_HOSTNAME + HOSTNAME_INFRA_SUFFIX,
             constants.STORAGE_1_HOSTNAME,
             constants.NETWORK_TYPE_INFRA),

            (constants.CONTROLLER_CGCS_NFS,
             constants.CONTROLLER_CGCS_NFS,
             constants.NETWORK_TYPE_INFRA),
        ]

        hosts = {}
        for hostname, name, networktype in hostnames:
            try:
                address = self._get_address_by_name(name, networktype)
                hosts.update({hostname: {'ip': address.address}})
            except exception.AddressNotFoundByName:
                pass
        return {
            'platform::config::params::hosts': hosts
        }

    def _get_host_upgrade_config(self, host):
        config = {}
        try:
            upgrade = self.dbapi.software_upgrade_get_one()
        except exception.NotFound:
            return config

        upgrade_states = [constants.UPGRADE_ACTIVATING,
                          constants.UPGRADE_ACTIVATION_FAILED,
                          constants.UPGRADE_ACTIVATION_COMPLETE,
                          constants.UPGRADE_COMPLETED]
        # we don't need compatibility mode after we activate
        if upgrade.state in upgrade_states:
            config.update({
                'neutron::server::vhost_user_enabled': True
            })
            return config

        upgrade_load_id = upgrade.to_load

        # TODO: update the nova upgrade level for Pike
        host_upgrade = self.dbapi.host_upgrade_get_by_host(host['id'])
        if host_upgrade.target_load == upgrade_load_id:
            from_load = self.dbapi.load_get(upgrade.from_load)
            sw_version = from_load.software_version
            nova_level = NOVA_UPGRADE_LEVELS.get(sw_version)

            if not nova_level:
                raise exception.SysinvException(
                    ("No matching upgrade level found for version %s")
                    % sw_version)

            config.update({
                  'nova::upgrade_level_compute': nova_level
            })

        return config

    def _get_amqp_config(self):
        return {
            'platform::amqp::params::host':
                self._get_management_address(),
            'platform::amqp::params::host_url':
                self._format_url_address(self._get_management_address()),
        }

    def _get_resolv_config(self):
        servers = [self._get_management_address()]

        dns = self.dbapi.idns_get_one()
        if dns.nameservers:
            servers += dns.nameservers.split(',')

        return {
            'platform::dns::resolv::servers': servers
        }

    def _get_user_config(self):
        user = self.dbapi.iuser_get_one()
        return {
            'platform::users::params::wrsroot_password':
                user.passwd_hash,
            'platform::users::params::wrsroot_password_max_age':
                user.passwd_expiry_days,
        }

    def _get_haproxy_config(self):
        public_address = self._get_address_by_name(
            constants.CONTROLLER, constants.NETWORK_TYPE_OAM)
        private_address = self._get_address_by_name(
            constants.CONTROLLER, constants.NETWORK_TYPE_MGMT)

        https_enabled = self._https_enabled()

        config = {
            'platform::haproxy::params::public_ip_address':
                public_address.address,
            'platform::haproxy::params::private_ip_address':
                private_address.address,
            'platform::haproxy::params::enable_https':
                https_enabled,
        }

        try:
            tpmconfig = self.dbapi.tpmconfig_get_one()
            if tpmconfig.tpm_path:
                config.update({
                    'platform::haproxy::params::tpm_object': tpmconfig.tpm_path
                })
        except exception.NotFound:
            pass

        return config

    def _get_sdn_config(self):
        return {
            'platform::params::sdn_enabled': self._sdn_enabled()
        }

    def _get_region_config(self):
        if not self._region_config():
            return {}

        region_1_name = self._operator.keystone.get_region_name()
        region_2_name = self._region_name()
        return {
            'platform::params::region_config': self._region_config(),
            'platform::params::region_1_name': region_1_name,
            'platform::params::region_2_name': region_2_name,
        }

    def _get_distributed_cloud_role(self):
        if self._distributed_cloud_role() is None:
            return {}

        return {
            'platform::params::distributed_cloud_role': self._distributed_cloud_role(),
        }

    def _get_sm_config(self):
        multicast_address = self._get_address_by_name(
            constants.SM_MULTICAST_MGMT_IP_NAME,
            constants.NETWORK_TYPE_MULTICAST)
        return {
            'platform::sm::params::mgmt_ip_multicast':
                multicast_address.address,
            'platform::sm::params::infra_ip_multicast':
                multicast_address.address,
        }

    def _get_firewall_config(self):
        config = {}
        rules_filepath = os.path.join(tsconfig.PLATFORM_CONF_PATH,
                                      'iptables.rules')
        if os.path.isfile(rules_filepath):
            config.update({
                'platform::firewall::oam::rules_file': rules_filepath
            })
        return config

    def _get_host_platform_config(self, host, config_uuid):
        if not config_uuid:
            config_uuid = host.config_target

        # required parameters
        config = {
            'platform::params::hostname': host.hostname,
            'platform::params::software_version': host.software_load,
        }

        # optional parameters
        if config_uuid:
            config.update({
                'platform::config::params::config_uuid': config_uuid
            })

        if host.personality == constants.CONTROLLER:

            controller0_address = self._get_address_by_name(
                constants.CONTROLLER_0_HOSTNAME, constants.NETWORK_TYPE_MGMT)

            controller1_address = self._get_address_by_name(
                constants.CONTROLLER_1_HOSTNAME, constants.NETWORK_TYPE_MGMT)

            if host.hostname == constants.CONTROLLER_0_HOSTNAME:
                mate_hostname = constants.CONTROLLER_1_HOSTNAME
                mate_address = controller1_address
            else:
                mate_hostname = constants.CONTROLLER_0_HOSTNAME
                mate_address = controller0_address

            config.update({
                'platform::params::controller_0_ipaddress':
                    controller0_address.address,
                'platform::params::controller_1_ipaddress':
                    controller1_address.address,
                'platform::params::controller_0_hostname':
                    constants.CONTROLLER_0_HOSTNAME,
                'platform::params::controller_1_hostname':
                    constants.CONTROLLER_1_HOSTNAME,
                'platform::params::mate_hostname': mate_hostname,
                'platform::params::mate_ipaddress': mate_address.address,
            })

        system = self._get_system()
        config.update({
            'platform::params::system_name':
                system.name,
            'platform::params::system_mode':
                system.system_mode,
            'platform::params::system_type':
                system.system_type,
        })

        return config

    def _get_host_ntp_config(self, host):
        if host.personality == constants.CONTROLLER:
            ntp = self.dbapi.intp_get_one()
            servers = ntp.ntpservers.split(',') if ntp.ntpservers else []
        else:
            controller0_address = self._get_address_by_name(
                constants.CONTROLLER_0_HOSTNAME, constants.NETWORK_TYPE_MGMT)

            controller1_address = self._get_address_by_name(
                constants.CONTROLLER_1_HOSTNAME, constants.NETWORK_TYPE_MGMT)

            # All other hosts use the controller management IP addresses
            servers = [controller0_address.address,
                       controller1_address.address]

        # Logic behind setting the ntpdate_timeout:
        # If no servers are datafilled, the only one in
        # the list is the other controller.  When the first
        # controller is brought up, the other one doesn't
        # exist to respond, so we will always wait and timeout.
        # When the second controller is brought up, it will
        # always go to the active controller which should be
        # there and respond quickly.  So the compromise between
        # these two controller situations is a 30 second timeout.
        #
        # The 180 second timeout is used to cover for a 3 server +
        # peer controller situation where 2 DNS servers are
        # provided and neither DNS server responds to queries. The
        # longer timeout here will allow access to all 3 servers to
        # timeout and yet still have enough time to talk to and get
        # a useable response out of the peer controller.
        #
        # Also keep in mind that ntpdate's role is to bring
        # errant system clocks that are more than 1000 seconds from
        # reality back into line.  If the system clock is under 1000
        # seconds out, the ntpd will bring it back in line anyway,
        # and 11 minute mode will keep it accurate.  It also helps
        # minimize system clock stepping by ntpd, the likes of which
        # may occur 15-20 minutes after reboot when ntpd finally
        # decides what to do after analyzing all servers available
        # to it.  This clock stepping can be disruptive to the
        # system and thus we have ntpdate in place to minimize that.
        if servers:
            ntpdate_timeout = "180"
        else:
            ntpdate_timeout = "30"

        return {
            'platform::ntp::servers': servers,
            'platform::ntp::ntpdate_timeout': ntpdate_timeout,
        }

    def _get_host_sysctl_config(self, host):
        config = {}

        if host.personality == constants.CONTROLLER:
            remotelogging = self.dbapi.remotelogging_get_one()

            ip_forwarding = (self._region_config() or
                             self._sdn_enabled() or
                             remotelogging.enabled)

            # The forwarding IP version is based on the OAM network version
            address = self._get_address_by_name(
                constants.CONTROLLER_HOSTNAME, constants.NETWORK_TYPE_OAM)

            ip_version = address.family

            config.update({
                'platform::sysctl::params::ip_forwarding': ip_forwarding,
                'platform::sysctl::params::ip_version': ip_version,
            })

        if constants.LOWLATENCY in host.subfunctions:
            config.update({
                'platform::sysctl::params::low_latency': True
            })

        return config

    def _get_drbd_sync_config(self):
        drbdconfig = self.dbapi.drbdconfig_get_one()
        return {
            'platform::drbd::params::link_util': str(drbdconfig.link_util),
            'platform::drbd::params::link_speed': self._get_drbd_link_speed(),
            'platform::drbd::params::num_parallel': str(drbdconfig.num_parallel),
            'platform::drbd::params::rtt_ms': str(drbdconfig.rtt_ms),
        }

    def _get_host_drbd_config(self, host):
        config = {}
        system = self._get_system()
        if system.system_type == constants.TIS_AIO_BUILD:
            # restrict DRBD syncing to platform cores/threads
            platform_cpus = self._get_host_cpu_list(
                host, function=constants.PLATFORM_FUNCTION, threads=True)

            # build a hex bitmap of the platform cores
            platform_cpumask = 0
            for cpu in platform_cpus:
                platform_cpumask |= 1 << cpu.cpu

            drbd_cpumask = '%x' % platform_cpumask

            config.update({
                'platform::drbd::params::cpumask': drbd_cpumask
            })
        return config

    def _get_drbd_link_speed(self):
        # return infra link speed if provisioned, otherwise mgmt
        try:
            infra_network = self.dbapi.network_get_by_type(
                constants.NETWORK_TYPE_INFRA)
            drbd_link_speed = infra_network.link_capacity
        except exception.NetworkTypeNotFound:
            mgmt_network = self.dbapi.network_get_by_type(
                constants.NETWORK_TYPE_MGMT)
            drbd_link_speed = mgmt_network.link_capacity

        return drbd_link_speed

    def _get_nfs_config(self):

        # Calculate the optimal NFS r/w size based on the network mtu based
        # on the configured network(s)
        try:
            infra_network = self.dbapi.network_get_by_type(
                constants.NETWORK_TYPE_INFRA)
            mtu = infra_network.mtu
        except exception.NetworkTypeNotFound:
            mgmt_network = self.dbapi.network_get_by_type(
                constants.NETWORK_TYPE_MGMT)
            mtu = mgmt_network.mtu

        if self._get_address_by_name(
                constants.CONTROLLER_PLATFORM_NFS,
                constants.NETWORK_TYPE_MGMT).family == constants.IPV6_FAMILY:
            nfs_proto = 'udp6'
        else:
            nfs_proto = 'udp'

        # round to the nearest 1k of the MTU
        nfs_rw_size = (mtu / 1024) * 1024

        return {
            'platform::params::nfs_rw_size': nfs_rw_size,
            'platform::params::nfs_proto': nfs_proto,
        }

    def _get_remotelogging_config(self):
        remotelogging = self.dbapi.remotelogging_get_one()

        return {
            'platform::remotelogging::params::enabled':
                remotelogging.enabled,
            'platform::remotelogging::params::ip_address':
                remotelogging.ip_address,
            'platform::remotelogging::params::port':
                remotelogging.port,
            'platform::remotelogging::params::transport':
                remotelogging.transport,
        }

    def _get_snmp_config(self):
        system = self.dbapi.isystem_get_one()
        comm_strs = self.dbapi.icommunity_get_list()
        trapdests = self.dbapi.itrapdest_get_list()

        config = {
            'platform::snmp::params::system_name':
                system.name,
            'platform::snmp::params::system_location':
                system.location,
            'platform::snmp::params::system_contact':
                system.contact,
        }

        if comm_strs is not None:
            comm_list = []
            for i in comm_strs:
                comm_list.append(i.community)
            config.update({'platform::snmp::params::community_strings':
                           comm_list})

        if trapdests is not None:
            trap_list = []
            for e in trapdests:
                trap_list.append(e.ip_address + ' ' + e.community)
            config.update({'platform::snmp::params::trap_destinations':
                           trap_list})

        return config