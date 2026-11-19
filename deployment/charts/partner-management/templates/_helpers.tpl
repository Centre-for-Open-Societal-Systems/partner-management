{{/*
Shared component helpers. Each component template builds a component-scoped
context (its own values merged with global) and calls these, so one set of
helpers serves staff-portal-api, partner-api and staff-portal-ui.
*/}}

{{- define "pm.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{ default (include "common.names.fullname" .) .Values.serviceAccount.name }}
{{- else -}}
{{ default "default" .Values.serviceAccount.name }}
{{- end -}}
{{- end -}}

{{- define "pm.imagePullSecrets" -}}
{{- include "common.images.pullSecrets" (dict "images" (list .Values.image) "global" .Values.global) -}}
{{- end -}}

{{- define "pm.baseEnvVars" -}}
{{- $context := .context -}}
{{- range $k, $v := .envVars }}
- name: {{ $k }}
{{- if or (kindIs "int64" $v) (kindIs "float64" $v) (kindIs "bool" $v) }}
  value: {{ $v | quote }}
{{- else if kindIs "string" $v }}
  value: {{ include "common.tplvalues.render" ( dict "value" $v "context" $context ) | squote }}
{{- else }}
  valueFrom: {{- include "common.tplvalues.render" ( dict "value" $v "context" $context ) | nindent 4 }}
{{- end }}
{{- end }}
{{- end -}}

{{- define "pm.envVars" -}}
{{- $envVars := merge (deepCopy .Values.envVars) (deepCopy .Values.envVarsFrom) -}}
{{- include "pm.baseEnvVars" (dict "envVars" $envVars "context" $) }}
{{- end -}}

{{/*
staffPortalApi.catalogueSources as compact JSON: a list, or a YAML/JSON string
(Rancher's multiline form field); empty = []. A ' is written as \u0027 (the env
value is single-quoted).
*/}}
{{/*
staffPortalApi.bootstrapPartners as compact JSON, as pm.catalogueSourcesJson;
partnerId, jwksUrl, name and description are templated.
*/}}
{{- define "pm.bootstrapPartnersJson" -}}
{{- $v := .Values.bootstrapPartners | default list -}}
{{- if kindIs "string" $v -}}
{{- $v = fromYamlArray $v -}}
{{- end -}}
{{- $out := list -}}
{{- range $v -}}
{{- $id := tpl (.partnerId | default "") $ | trim -}}
{{- $url := tpl (.jwksUrl | default "") $ | trim -}}
{{- /* An entry that renders without a partner ID or URL is skipped (e.g. a
       conditional default in an umbrella chart). */ -}}
{{- if and $id $url -}}
{{- $out = append $out (dict "partner_id" $id "jwks_url" $url "name" (tpl (.name | default "") $) "description" (tpl (.description | default "") $)) -}}
{{- end -}}
{{- end -}}
{{- $out | toJson | replace "'" "\\u0027" -}}
{{- end -}}

{{- define "pm.catalogueSourcesJson" -}}
{{- $v := .Values.catalogueSources | default list -}}
{{- if kindIs "string" $v -}}
{{- $v = fromYamlArray $v -}}
{{- end -}}
{{- $v | toJson | replace "'" "\\u0027" -}}
{{- end -}}
