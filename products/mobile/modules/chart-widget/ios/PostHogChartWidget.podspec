require 'json'

package = JSON.parse(File.read(File.join(__dir__, '..', 'package.json')))

# Not named ChartWidget: the widget extension target owns the HedgehogWidget Swift module, and a pod named after a
# widget kind would shadow it the same way.
Pod::Spec.new do |s|
  s.name           = 'PostHogChartWidget'
  s.version        = package['version']
  s.summary        = 'Hands the session and pin catalog to the iOS Chart home-screen widget'
  s.license        = 'MIT'
  s.author         = 'PostHog'
  s.homepage       = 'https://posthog.com'
  s.platforms      = { :ios => '16.4' }
  s.swift_version  = '5.9'
  s.source         = { git: 'https://github.com/PostHog/posthog.git' }
  s.static_framework = true

  s.dependency 'ExpoModulesCore'
  s.frameworks = 'WidgetKit', 'Security'

  s.source_files = '**/*.{h,m,swift}'
  s.pod_target_xcconfig = {
    'DEFINES_MODULE' => 'YES',
    'SWIFT_COMPILATION_MODE' => 'wholemodule'
  }
end
