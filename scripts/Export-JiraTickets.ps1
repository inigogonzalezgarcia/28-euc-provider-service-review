<#
.SYNOPSIS
    Read-only export of Jira Service Management tickets to the tickets.csv format used by eucreview.

.DESCRIPTION
    Pages through the Jira Cloud REST API (/rest/api/3/search) with a JQL filter and writes one row per issue
    with the columns eucreview understands: id, type, priority, created, first_response, resolved, updated,
    status, team, tier, site, category, channel, reopened, escalated_to, escalated_at, pending_hours, csat, fcr,
    vip, summary.

    It only reads. Authentication is a Jira API token typed into the Get-Credential prompt (user = your Atlassian
    e-mail, password = the token); nothing is stored. Custom field ids differ per Jira site: check the ones at the
    top of the script against your instance (Project settings > Fields, or /rest/api/3/field).

.PARAMETER Site
    Your Jira Cloud site, e.g. https://contoso.atlassian.net

.PARAMETER Jql
    Which issues to export. Default: a service desk project, created in the last 2 months, plus anything still open.

.PARAMETER OutputPath
    Where to write the CSV. Default: .\data\tickets.csv

.EXAMPLE
    .\scripts\Export-JiraTickets.ps1 -Site https://contoso.atlassian.net -Jql 'project = SD AND created >= -60d' -OutputPath .\data\tickets.csv
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Site,
    [string] $Jql = 'project = SD AND (created >= -60d OR resolution = Unresolved) ORDER BY created ASC',
    [string] $OutputPath = '.\data\tickets.csv'
)

# ---- field mapping: adjust to your instance --------------------------------------------------------------
$Fields = @{
    FirstResponse = 'customfield_10040'   # "Time to first response" SLA field, or a date field your workflow fills
    Team          = 'customfield_10001'   # Team / assignment group
    Tier          = 'customfield_10101'   # Support level (L1/L2/L3)
    Site          = 'customfield_10102'   # Office / location
    Category      = 'customfield_10103'   # Category / service
    Channel       = 'customfield_10006'   # Request type / channel
    Reopened      = 'customfield_10104'   # Reopen count (number)
    EscalatedTo   = 'customfield_10105'   # Escalated to (team)
    EscalatedAt   = 'customfield_10106'   # Escalated at (date-time)
    PendingHours  = 'customfield_10107'   # Hours in "Waiting for customer" (number), or derive it from the changelog
    Csat          = 'customfield_10044'   # Satisfaction (1-5)
    Fcr           = 'customfield_10108'   # First contact resolution (Yes/No)
    Vip           = 'customfield_10109'   # VIP (Yes/No)
}

$cred = Get-Credential -Message 'Atlassian e-mail and API token (read-only)'
$pair = '{0}:{1}' -f $cred.UserName, $cred.GetNetworkCredential().Password
$headers = @{ Authorization = 'Basic ' + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair)); Accept = 'application/json' }
$pair = $null

function Get-Val($issue, $key) {
    if (-not $key) { return '' }
    $v = $issue.fields.$key
    if ($null -eq $v) { return '' }
    if ($v -is [string]) { return $v }
    if ($v.PSObject.Properties['value']) { return $v.value }
    if ($v.PSObject.Properties['name']) { return $v.name }
    if ($v.PSObject.Properties['completedCycles']) {            # Jira SLA field: take the first cycle's stop time
        $c = @($v.completedCycles)[0]; if ($c) { return $c.stopTime.jira }
        if ($v.ongoingCycle) { return '' }
    }
    return [string] $v
}

function Fmt-Date($s) {
    if (-not $s) { return '' }
    try { return ([datetime]::Parse($s)).ToString('yyyy-MM-dd HH:mm') } catch { return '' }
}

$fieldList = @('issuetype', 'priority', 'created', 'resolutiondate', 'updated', 'status', 'summary') + $Fields.Values
$rows = New-Object System.Collections.Generic.List[object]
$startAt = 0
do {
    $body = @{ jql = $Jql; startAt = $startAt; maxResults = 100; fields = $fieldList } | ConvertTo-Json -Depth 4
    $resp = Invoke-RestMethod -Method Post -Uri "$Site/rest/api/3/search" -Headers $headers -ContentType 'application/json' -Body $body
    foreach ($i in $resp.issues) {
        $rows.Add([pscustomobject]@{
            id             = $i.key
            type           = $i.fields.issuetype.name
            priority       = $i.fields.priority.name
            created        = Fmt-Date $i.fields.created
            first_response = Fmt-Date (Get-Val $i $Fields.FirstResponse)
            resolved       = Fmt-Date $i.fields.resolutiondate
            updated        = Fmt-Date $i.fields.updated
            status         = $i.fields.status.name
            team           = Get-Val $i $Fields.Team
            tier           = Get-Val $i $Fields.Tier
            site           = Get-Val $i $Fields.Site
            category       = Get-Val $i $Fields.Category
            channel        = Get-Val $i $Fields.Channel
            reopened       = Get-Val $i $Fields.Reopened
            escalated_to   = Get-Val $i $Fields.EscalatedTo
            escalated_at   = Fmt-Date (Get-Val $i $Fields.EscalatedAt)
            pending_hours  = Get-Val $i $Fields.PendingHours
            csat           = Get-Val $i $Fields.Csat
            fcr            = Get-Val $i $Fields.Fcr
            vip            = Get-Val $i $Fields.Vip
            summary        = $i.fields.summary
        })
    }
    $startAt += 100
    Write-Progress -Activity 'Exporting' -Status "$($rows.Count) of $($resp.total)" -PercentComplete ([math]::Min(100, 100 * $rows.Count / [math]::Max(1, $resp.total)))
} while ($startAt -lt $resp.total)

$dir = Split-Path -Parent $OutputPath
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
$rows | Export-Csv -Path $OutputPath -NoTypeInformation -Encoding UTF8
Write-Host "$($rows.Count) tickets written to $OutputPath"
