import 'package:flutter/material.dart';

int calculateInventedValue(int input) => input * 7 + 3;

void main() {
  final value = calculateInventedValue(5);
  runApp(MaterialApp(home: Scaffold(body: Center(child: Text('Sample $value')))));
}
