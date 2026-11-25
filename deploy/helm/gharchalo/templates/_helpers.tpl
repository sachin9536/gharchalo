{{- define "gharchalo.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "gharchalo.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/* usage: include "gharchalo.selector" (list . "api") */}}
{{- define "gharchalo.selector" -}}
{{- $root := index . 0 -}}
app.kubernetes.io/name: {{ $root.Chart.Name }}
app.kubernetes.io/instance: {{ $root.Release.Name }}
app.kubernetes.io/component: {{ index . 1 }}
{{- end -}}

{{- define "gharchalo.databaseUrl" -}}
{{- if .Values.postgres.enabled -}}
{{- printf "postgresql+psycopg://%s:%s@%s-postgres:5432/%s" .Values.postgres.user .Values.postgres.password (include "gharchalo.fullname" .) .Values.postgres.database -}}
{{- else -}}
{{- required "externalDatabaseUrl is required when postgres.enabled=false" .Values.externalDatabaseUrl -}}
{{- end -}}
{{- end -}}

{{- define "gharchalo.sarvamSecretName" -}}
{{- default (printf "%s-sarvam" (include "gharchalo.fullname" .)) .Values.api.sarvam.existingSecret -}}
{{- end -}}
