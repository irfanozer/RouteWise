targetScope = 'resourceGroup'

metadata name = 'RouteWise Azure foundation'
metadata description = 'Private PostgreSQL, networking, logs, and a Container Apps environment.'

param location string = resourceGroup().location

@minLength(3)
@maxLength(15)
param namePrefix string = 'routewise'

@minLength(2)
@maxLength(7)
param environmentName string = 'prod'

@minLength(1)
@maxLength(63)
param postgresAdministratorLogin string = 'routewise_admin'

@secure()
@minLength(8)
@maxLength(128)
param postgresAdministratorPassword string

@minLength(1)
@maxLength(63)
param postgresDatabaseName string = 'routewise'

@allowed([
  '16'
  '17'
])
param postgresVersion string = '17'

param postgresSkuName string = 'Standard_B1ms'

@minValue(32)
param postgresStorageSizeGB int = 32

param tags object = {}

var normalizedPrefix = toLower(namePrefix)
var normalizedEnvironment = toLower(environmentName)
var suffix = '${normalizedPrefix}-${normalizedEnvironment}'
var resourceTags = union({
  application: 'RouteWise'
  environment: normalizedEnvironment
  managedBy: 'Bicep'
  workload: 'public-demo'
}, tags)
var virtualNetworkName = 'vnet-${suffix}'
var logAnalyticsWorkspaceName = 'log-${suffix}'
var containerAppsEnvironmentName = 'cae-${suffix}'
var postgresPrivateDnsZoneName = '${normalizedPrefix}.postgres.database.azure.com'
var postgresServerName = take('psql-${suffix}-${uniqueString(subscription().subscriptionId, resourceGroup().id)}', 63)

resource virtualNetwork 'Microsoft.Network/virtualNetworks@2025-05-01' = {
  name: virtualNetworkName
  location: location
  tags: resourceTags
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.47.0.0/16'
      ]
    }
  }
}

resource containerAppsSubnet 'Microsoft.Network/virtualNetworks/subnets@2025-05-01' = {
  parent: virtualNetwork
  name: 'snet-container-apps'
  properties: {
    addressPrefix: '10.47.0.0/24'
    delegations: [
      {
        name: 'container-apps-environment-delegation'
        properties: {
          serviceName: 'Microsoft.App/environments'
        }
      }
    ]
  }
}

resource postgresSubnet 'Microsoft.Network/virtualNetworks/subnets@2025-05-01' = {
  parent: virtualNetwork
  name: 'snet-postgres'
  properties: {
    addressPrefix: '10.47.1.0/27'
    delegations: [
      {
        name: 'postgres-flexible-server-delegation'
        properties: {
          serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers'
        }
      }
    ]
  }
}

resource postgresPrivateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: postgresPrivateDnsZoneName
  location: 'global'
  tags: resourceTags
}

resource postgresPrivateDnsVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: postgresPrivateDnsZone
  name: 'link-${virtualNetworkName}'
  location: 'global'
  tags: resourceTags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetwork.id
    }
  }
}

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2025-07-01' = {
  name: logAnalyticsWorkspaceName
  location: location
  tags: resourceTags
  properties: {
    features: {
      disableLocalAuth: false
      enableLogAccessUsingOnlyResourcePermissions: true
    }
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
    retentionInDays: 30
    sku: {
      name: 'PerGB2018'
    }
    workspaceCapping: {
      dailyQuotaGb: 1
    }
  }
}

resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2026-01-01' = {
  name: containerAppsEnvironmentName
  location: location
  tags: resourceTags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsWorkspace.properties.customerId
        sharedKey: logAnalyticsWorkspace.listKeys().primarySharedKey
      }
    }
    peerTrafficConfiguration: {
      encryption: {
        enabled: true
      }
    }
    vnetConfiguration: {
      infrastructureSubnetId: containerAppsSubnet.id
      internal: false
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    zoneRedundant: false
  }
}

resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2025-08-01' = {
  name: postgresServerName
  location: location
  tags: resourceTags
  sku: {
    name: postgresSkuName
    tier: 'Burstable'
  }
  properties: {
    administratorLogin: postgresAdministratorLogin
    administratorLoginPassword: postgresAdministratorPassword
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    createMode: 'Create'
    dataEncryption: {
      type: 'SystemManaged'
    }
    highAvailability: {
      mode: 'Disabled'
    }
    network: {
      delegatedSubnetResourceId: postgresSubnet.id
      privateDnsZoneArmResourceId: postgresPrivateDnsZone.id
      publicNetworkAccess: 'Disabled'
    }
    storage: {
      autoGrow: 'Disabled'
      storageSizeGB: postgresStorageSizeGB
    }
    version: postgresVersion
  }
  dependsOn: [
    postgresPrivateDnsVnetLink
  ]
}

resource postgresDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2025-08-01' = {
  parent: postgresServer
  name: postgresDatabaseName
  properties: {}
}

output containerAppsEnvironmentName string = containerAppsEnvironment.name
output postgresServerName string = postgresServer.name
output postgresServerFqdn string = postgresServer.properties.fullyQualifiedDomainName
output postgresDatabaseName string = postgresDatabase.name
output postgresAdministratorLogin string = postgresAdministratorLogin

