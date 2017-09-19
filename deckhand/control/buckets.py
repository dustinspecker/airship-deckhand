# Copyright 2017 AT&T Intellectual Property.  All other rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import yaml

import falcon
from oslo_log import log as logging

from deckhand.control import base as api_base
from deckhand.control.views import document as document_view
from deckhand.db.sqlalchemy import api as db_api
from deckhand.engine import document_validation
from deckhand.engine import secrets_manager
from deckhand import errors as deckhand_errors
from deckhand import types

LOG = logging.getLogger(__name__)


class BucketsResource(api_base.BaseResource):
    """API resource for realizing CRUD operations for buckets."""

    view_builder = document_view.ViewBuilder()
    secrets_mgr = secrets_manager.SecretsManager()

    def on_put(self, req, resp, bucket_name=None):
        document_data = req.stream.read(req.content_length or 0)
        try:
            documents = list(yaml.safe_load_all(document_data))
        except yaml.YAMLError as e:
            error_msg = ("Could not parse the document into YAML data. "
                         "Details: %s." % e)
            LOG.error(error_msg)
            raise falcon.HTTPBadRequest(description=e.format_message())

        # All concrete documents in the payload must successfully pass their
        # JSON schema validations. Otherwise raise an error.
        try:
            validation_policies = document_validation.DocumentValidation(
                documents).validate_all()
        except deckhand_errors.InvalidDocumentFormat as e:
            raise falcon.HTTPBadRequest(description=e.format_message())

        for document in documents:
            if any([document['schema'].startswith(t)
                    for t in types.DOCUMENT_SECRET_TYPES]):
                secret_data = self.secrets_mgr.create(document)
                document['data'] = secret_data

        try:
            documents.extend(validation_policies)
            created_documents = db_api.documents_create(bucket_name, documents)
        except deckhand_errors.DocumentExists as e:
            raise falcon.HTTPConflict(description=e.format_message())
        except Exception as e:
            raise falcon.HTTPInternalServerError(description=e)

        if created_documents:
            resp.body = self.to_yaml_body(
                self.view_builder.list(created_documents))
        resp.status = falcon.HTTP_200
        resp.append_header('Content-Type', 'application/x-yaml')