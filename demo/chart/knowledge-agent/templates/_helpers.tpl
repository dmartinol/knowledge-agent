{{- define "knowledge-agent.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "knowledge-agent.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "knowledge-agent.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "knowledge-agent.labels" -}}
helm.sh/chart: {{ include "knowledge-agent.chart" . }}
app.kubernetes.io/name: {{ include "knowledge-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: knowledge-agent-demo
{{- end -}}

{{- define "knowledge-agent.agent.name" -}}
{{- include "knowledge-agent.fullname" . -}}
{{- end -}}

{{- define "knowledge-agent.ui.name" -}}
{{- printf "%s-ui" (include "knowledge-agent.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "knowledge-agent.lcore.name" -}}
{{- printf "%s-lcore" (include "knowledge-agent.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "knowledge-agent.agent.selectorLabels" -}}
app.kubernetes.io/name: {{ include "knowledge-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: agent
{{- end -}}

{{- define "knowledge-agent.ui.selectorLabels" -}}
app.kubernetes.io/name: {{ include "knowledge-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: ui
{{- end -}}

{{- define "knowledge-agent.lcore.selectorLabels" -}}
app.kubernetes.io/name: {{ include "knowledge-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: lcore
{{- end -}}

{{- define "knowledge-agent.agent.image" -}}
{{- $repo := .Values.agent.image.repository -}}
{{- if not $repo -}}
{{- $repo = printf "%s/%s/%s" .Values.image.internalRegistry .Release.Namespace .Values.agent.image.stream -}}
{{- end -}}
{{- printf "%s:%s" $repo (.Values.agent.image.tag | toString) -}}
{{- end -}}

{{- define "knowledge-agent.ui.image" -}}
{{- $repo := .Values.ui.image.repository -}}
{{- if not $repo -}}
{{- $repo = printf "%s/%s/%s" .Values.image.internalRegistry .Release.Namespace .Values.ui.image.stream -}}
{{- end -}}
{{- printf "%s:%s" $repo (.Values.ui.image.tag | toString) -}}
{{- end -}}

{{- define "knowledge-agent.lcore.image" -}}
{{- printf "%s:%s" .Values.lcore.image.repository (.Values.lcore.image.tag | toString) -}}
{{- end -}}

{{- define "knowledge-agent.lcoreCardUrl" -}}
{{- if .Values.lcore.enabled -}}
{{- printf "http://%s:%v/.well-known/agent-card.json" (include "knowledge-agent.lcore.name" .) .Values.lcore.port -}}
{{- else if .Values.lcore.externalUrl -}}
{{- printf "%s/.well-known/agent-card.json" (trimSuffix "/" .Values.lcore.externalUrl) -}}
{{- else -}}
{{- fail "lcore.enabled=false requires lcore.externalUrl" -}}
{{- end -}}
{{- end -}}

{{- define "knowledge-agent.agent.publicUrl" -}}
{{- if .Values.agent.publicUrl -}}
{{- trimSuffix "/" .Values.agent.publicUrl -}}
{{- else if and .Values.agent.route.enabled .Values.agent.route.host -}}
{{- printf "https://%s" .Values.agent.route.host -}}
{{- end -}}
{{- end -}}

{{- define "knowledge-agent.secretName" -}}
{{- required "secrets.existingSecret is required; create the Secret first (see values-secret.yaml.example)" .Values.secrets.existingSecret -}}
{{- end -}}

{{- define "knowledge-agent.securityContext" -}}
allowPrivilegeEscalation: false
capabilities:
  drop:
    - ALL
runAsNonRoot: true
seccompProfile:
  type: RuntimeDefault
{{- end -}}
