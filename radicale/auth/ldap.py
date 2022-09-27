# This file is part of Radicale - CalDAV and CardDAV server
# Copyright 2022 Peter Varkoly
#
# This library is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Radicale.  If not, see <http://www.gnu.org/licenses/>.
"""
Authentication backend that checks credentials with a ldap server.
Following parameters are needed in the configuration
   ldap_uri       The ldap url to the server like ldap://localhost
   ldap_base      The baseDN of the ldap server
   ldap_reader_dn The DN of a ldap user with read access to get the user accounts
   ldap_secret    The password of the ldap_reader_dn
   ldap_filter    The search filter to find the user to authenticate by the username
   ldap_load_groups If the groups of the authenticated users need to be loaded
   ldaps_certificate The path to a certificate to validate ldaps with
"""

import os
import ldap
from radicale import auth, config
from radicale.log import logger


class Auth(auth.BaseAuth):
    _ldap_uri: str
    _ldap_base: str
    _ldap_reader_dn: str
    _ldap_secret: str
    _ldap_filter: str
    _ldap_load_groups: bool

    def __init__(self, configuration: config.Configuration) -> None:
        super().__init__(configuration)
        self._ldap_uri = configuration.get("auth", "ldap_uri")
        self._ldap_base = configuration.get("auth", "ldap_base")

        # Load LDAP reader details via env first if available
        self._ldap_reader_dn = os.environ.get("AUTH__LDAP_READER_DN", configuration.get("auth", "ldap_reader_dn"))
        self._ldap_secret = os.environ.get("AUTH__LDAP_SECRET", configuration.get("auth", "ldap_secret"))

        self._ldap_load_groups = configuration.get("auth", "ldap_load_groups")
        self._ldap_filter = configuration.get("auth", "ldap_filter")
        self._ldaps_certificate = configuration.get("auth", "ldaps_certificate")
        # If a ldaps_certificate is set, configure ldap to use it
        if self._ldaps_certificate:
            ldap.set_option(ldap.OPT_X_TLS_CACERTFILE, self._ldaps_certificate)

    def login(self, login: str, password: str) -> str:
        """Validate credentials.
        In first step we make a connection to the ldap server with the ldap_reader_dn credential.
        In next step the DN of the user to authenticate will be searched.
        In the last step the authentication of the user will be proceeded.

        """
        try:
            """Bind as reader dn"""
            conn = ldap.initialize(self._ldap_uri)
            conn.protocol_version = 3
            conn.set_option(ldap.OPT_REFERRALS, 0)
            conn.simple_bind_s(self._ldap_reader_dn, self._ldap_secret)
            """Search for the dn of user to authenticate"""
            res = conn.search_s(
                self._ldap_base,
                ldap.SCOPE_SUBTREE,
                filterstr=self._ldap_filter.format(login),
                attrlist=["memberOf"],
            )
            if len(res) == 0:
                """User could not be found"""
                logger.debug("LDAP search returned no results.")
                return ""
            user_dn = res[0][0]
            logger.debug("LDAP Auth user: %s", user_dn)
            """Close ldap connection"""
            conn.unbind()
        except Exception:
            raise RuntimeError("Invalid ldap configuration")

        try:
            """Bind as user to authenticate"""
            conn = ldap.initialize(self._ldap_uri)
            conn.protocol_version = 3
            conn.set_option(ldap.OPT_REFERRALS, 0)
            conn.simple_bind_s(user_dn, password)
            tmp = []
            if self._ldap_load_groups:
                tmp = []
                for t in res[0][1]["memberOf"]:
                    tmp.append(t.decode("utf-8").split(",")[0][3:])
                self._ldap_groups = set(tmp)
                logger.debug(
                    "LDAP Auth groups of user: %s", ",".join(self._ldap_groups)
                )
            conn.unbind()
            return login
        except ldap.INVALID_CREDENTIALS:
            return ""
